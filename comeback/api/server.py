"""FastAPI app: the match stream (SSE), fan actions and broadcast overlay cues.

Run with ``python -m comeback`` and open http://localhost:8000.
"""

import asyncio
import json
import socket
import uuid
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from comeback.agents.llm import LLMGateway
from comeback.agents.speech import AUDIO_DIR
from comeback.api.replay import MATCHES_DIR, SPEEDS, ReplaySession, cue_visible, shared_crowd
from comeback.engine.match import load_match, run_engine
from comeback.fans.crowd import scaling_curve
from comeback.fans.profiles import for_match, load_profiles

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
SCALE_DIR = Path(__file__).resolve().parents[2] / "data" / "scale"
DEFAULT_MATCH = "demo-comeback"
KEEPALIVE_S = 15.0
IDLE_SESSION_S = 120.0   # a replay nobody watches is stopped (keeps the container idle and cheap)

# Every endpoint that touches a session is ``async``: it then runs on the event loop, like the replay
# itself. A plain ``def`` endpoint would run in a worker thread, concurrently with the replay loop
# (a seek could process events while the loop does: events counted twice or skipped).
sessions: dict[str, ReplaySession] = {}
gateway = LLMGateway()


@asynccontextmanager
async def lifespan(_: FastAPI):
    for path in sorted(MATCHES_DIR.glob("*.jsonl")):      # simulate each 10,000-fan audience once, before any viewer
        await asyncio.to_thread(shared_crowd, path.stem)
    yield
    for session in sessions.values():
        await session.stop()


app = FastAPI(title="COMEBACK", description="The AI that watches the match for you while you're away.",
              lifespan=lifespan)
NO_CACHE = {"Cache-Control": "no-cache"}   # always revalidate the UI: a stale module breaks the app silently


class UIStaticFiles(StaticFiles):
    """Static files for the web UI, revalidated on every load."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


app.mount("/web", UIStaticFiles(directory=WEB_DIR), name="web")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media/audio", StaticFiles(directory=AUDIO_DIR), name="audio")


def _match_path(match_id: str) -> Path:
    path = MATCHES_DIR / f"{match_id}.jsonl"
    if not path.is_file() or path.parent != MATCHES_DIR:
        raise HTTPException(404, f"unknown match {match_id!r}")
    return path


def _session(session_id: str) -> ReplaySession:
    if session_id not in sessions:
        raise HTTPException(404, "unknown session: open the stream first")
    return sessions[session_id]


def _profile(profile_id: str, match_id: str = DEFAULT_MATCH):
    """A demo fan, adapted to the fixture (the same side and shirt number in any match)."""
    profiles = load_profiles()
    if profile_id not in profiles:
        raise HTTPException(404, f"unknown profile {profile_id!r}")
    meta = _match_meta(match_id)
    return for_match(profiles[profile_id], meta["home"]["id"], meta["away"]["id"])


@cache
def _match_meta(match_id: str) -> dict[str, Any]:
    return load_match(_match_path(match_id))[0]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)


@app.get("/phone", include_in_schema=False)
def phone_page() -> FileResponse:
    """The fan's real phone: pairs with a control-room session through a QR code."""
    return FileResponse(WEB_DIR / "phone.html", headers=NO_CACHE)


@app.get("/api/lan")
def lan_address(request: Request) -> dict[str, Any]:
    """This machine's address on the local network, so a phone can reach the server (QR code)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # TEST-NET address: no packet is sent, it only picks the outgoing interface
            ip = s.getsockname()[0]
    except OSError:
        return {"url": None}
    return {"url": f"http://{ip}:{request.url.port or 80}"}


@app.get("/api/match/{match_id}")
def match_info(match_id: str) -> dict[str, Any]:
    """Fixture metadata, rosters (starters carry their formation spot) and scenario."""
    meta, events = load_match(_match_path(match_id))
    meta["duration_t"] = events[-1]["t"]
    return meta


@app.get("/api/matches")
def matches() -> list[dict[str, Any]]:
    """The matches this server can replay: the scripted demo and unscripted ones."""
    out = []
    for path in sorted(MATCHES_DIR.glob("*.jsonl")):
        meta = _match_meta(path.stem)
        out.append({"match_id": path.stem, "home": meta["home"]["name"], "away": meta["away"]["name"],
                    "scripted": meta.get("scenario") is not None})
    return out


@app.get("/api/profiles")
def profiles(match_id: str = DEFAULT_MATCH) -> list[dict[str, Any]]:
    return [_profile(pid, match_id).__dict__ for pid in load_profiles()]


@cache
def _overlays(match_id: str) -> list[dict[str, Any]]:
    meta, events = load_match(_match_path(match_id))
    return run_engine(meta, events).cues


@app.get("/api/overlays/{match_id}")
def overlays(match_id: str, profile: str | None = None) -> dict[str, Any]:
    """Timed, renderer-agnostic overlay cues for the whole match (optionally for one profile's level)."""
    cues = _overlays(match_id)
    if profile:
        level = _profile(profile, match_id).level
        cues = [c for c in cues if cue_visible(c, level)]
    return {"match_id": match_id, "count": len(cues), "cues": cues}


_scale_cache: dict[str, list[dict[str, int]]] = {}


@app.get("/api/scale/{match_id}")
async def scale(match_id: str) -> dict[str, Any]:
    """LLM calls needed to serve audiences of growing size (computed once, in a worker thread)."""
    if match_id not in _scale_cache:
        precomputed = SCALE_DIR / f"{match_id}.json"        # written at image build time
        if precomputed.is_file():
            _scale_cache[match_id] = json.loads(precomputed.read_text())
        else:
            meta, events = load_match(_match_path(match_id))
            _scale_cache[match_id] = await asyncio.to_thread(scaling_curve, meta, events)
    return {"match_id": match_id, "curve": _scale_cache[match_id]}


@app.get("/api/stream")
async def stream(request: Request, match_id: str = DEFAULT_MATCH, session: str | None = None,
                 profile: str = "omar", speed: int = 10, device: bool = False) -> StreamingResponse:
    """Server-Sent Events: events, snapshots, overlay cues, moment cards, alerts, catch-ups.

    ``device=true`` attaches a fan's phone to an existing session (never creates one).
    """
    _match_path(match_id)
    session_id = session or uuid.uuid4().hex[:12]
    replay = sessions.get(session_id)
    if device and replay is None:
        raise HTTPException(404, "no such session: scan the QR code shown in the control room")
    if replay is None or replay.match_id != match_id:
        replay = ReplaySession(session_id, match_id, _profile(profile, match_id), gateway, speed)
        sessions[session_id] = replay
    queue = replay.subscribe(device=device)
    replay.start()

    async def events():
        try:
            yield _sse("state", replay.state_message())
            while not await request.is_disconnected():
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(message["type"], message["data"])
        finally:
            replay.unsubscribe(queue)
            if not replay.watched:
                asyncio.create_task(_reap(session_id))

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _reap(session_id: str) -> None:
    await asyncio.sleep(IDLE_SESSION_S)
    replay = sessions.get(session_id)
    if replay and not replay.watched:
        sessions.pop(session_id, None)
        await replay.stop()


def _sse(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.get("/api/sessions")
async def live_sessions() -> list[dict[str, Any]]:
    """Live replay sessions (read by the MCP server)."""
    return [{"session": r.session_id, "match_id": r.match_id, "minute": r.brain.engine.state.minute,
             "period": r.brain.engine.state.period, "score": r.brain.engine.state.score_str(),
             "fan": r.fan.profile.name, "fan_present": r.fan.present} for r in sessions.values()]


@app.get("/api/session/{session_id}/live")
async def live_state(session_id: str) -> dict[str, Any]:
    """Current match state of a session: snapshot, danger reasons, verified moment cards."""
    replay = _session(session_id)
    engine = replay.brain.engine
    reasons = {code: tracker.reasons(engine.state.t) for code, tracker in engine.danger.items()}
    cards = [{k: c[k] for k in ("minute", "type", "team", "importance", "headline", "why_it_matters", "source")}
             for c in sorted(replay.brain.cards.values(), key=lambda c: c["t"]) if c["type"] != "danger_peak"]
    return {"snapshot": engine.snapshot(), "danger_reasons": reasons, "moments": cards,
            "fan": replay.fan.profile.name, "fan_present": replay.fan.present}


@app.get("/api/session/{session_id}/player/{player}")
async def player_stats(session_id: str, player: str) -> dict[str, Any]:
    """Live stats of one player, by id ("EMB-9") or by (part of) their name."""
    state = _session(session_id).brain.engine.state
    match = [pid for pid, info in state.roster.items()
             if pid.lower() == player.lower() or player.lower() in info["name"].lower()]
    if not match:
        raise HTTPException(404, f"no player matching {player!r}")
    pid = match[0]
    return {**state.roster[pid], "stats": state.players[pid].to_dict()}


@app.post("/api/session/{session_id}/away")
async def away(session_id: str) -> dict[str, Any]:
    return _session(session_id).go_away()


@app.post("/api/session/{session_id}/back")
async def back(session_id: str) -> JSONResponse:
    catchup = await _session(session_id).come_back()
    return JSONResponse(catchup or {"message": "already present"})


@app.post("/api/session/{session_id}/join")
async def join(session_id: str, minute: float = 60) -> dict[str, Any]:
    return await _session(session_id).join_at(minute)


@app.post("/api/session/{session_id}/seek")
async def seek(session_id: str, minute: float) -> dict[str, Any]:
    """Skip ahead while the fan keeps watching (used by the guided story)."""
    return _session(session_id).seek(minute)


@app.post("/api/session/{session_id}/schedule")
async def schedule(session_id: str, away: float | None = None, back: float | None = None) -> dict[str, Any]:
    """Plan the fan's absence at exact second-half minutes (used by the guided story)."""
    return _session(session_id).schedule(away, back)


@app.post("/api/session/{session_id}/settings")
async def alert_settings(session_id: str, alert_for: str | None = None, spoilers: bool | None = None,
                         night: bool | None = None) -> dict[str, Any]:
    """The fan's alert rules: "threat" | "equaliser" | "big", spoilers on/off, night mode on/off."""
    return _session(session_id).set_settings(alert_for, spoilers, night)


@app.post("/api/session/{session_id}/outage")
async def outage(session_id: str, down: bool = True) -> dict[str, Any]:
    """Failure drill: simulate an LLM outage for this session (agents fall back to verified templates)."""
    _session(session_id).set_outage(down)
    return {"down": down}


@app.post("/api/session/{session_id}/speed")
async def set_speed(session_id: str, value: int) -> dict[str, Any]:
    if value not in SPEEDS:
        raise HTTPException(400, f"speed must be one of {SPEEDS}")
    _session(session_id).set_speed(value)
    return {"speed": value}


@app.post("/api/session/{session_id}/pause")
async def pause(session_id: str, paused: bool = True) -> dict[str, Any]:
    _session(session_id).set_paused(paused)
    return {"paused": paused}


@app.post("/api/session/{session_id}/profile")
async def switch_profile(session_id: str, id: str) -> dict[str, Any]:
    replay = _session(session_id)
    replay.set_profile(_profile(id, replay.match_id))
    replay.away_bands = []  # viewing history belongs to the fan, not to the screen
    replay.publish("state", replay.state_message())
    return {"profile": id}
