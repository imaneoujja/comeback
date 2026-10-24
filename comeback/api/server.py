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
from comeback.api.replay import LIVE_MINUTE, MATCHES_DIR, SPEEDS, ReplaySession, cue_visible, shared_crowd
from comeback.engine.match import load_match, run_engine
from comeback.engine.state import KEY_PASS_WINDOW_S
from comeback.fans.crowd import scaling_curve
from comeback.fans.profiles import fan_profile, for_match, load_profiles

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


def _fan(match_id: str, side: str, lang: str, level: str, metric: str | None, player: str | None = None):
    """The fan as configured on the first screen (side, followed player, language, style, metric)."""
    meta = _match_meta(match_id)
    return fan_profile(side, lang, level, metric, meta["home"]["id"], meta["away"]["id"], player)


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


QUIET_XG = 1.0            # no goal and under 1.0 xG in total: "quiet so far"


@cache
def _live_view(match_id: str) -> dict[str, Any]:
    from comeback.engine.match import MatchEngine

    meta, events = load_match(_match_path(match_id))
    minute = LIVE_MINUTE.get(match_id, 0.0)
    engine = MatchEngine(meta)
    target = (2, minute) if minute >= 45 else (1, minute)
    index = next(i for i, e in enumerate(events) if (e["period"], e["minute"] + e["second"] / 60) >= target)
    for e in events[: index + 1]:
        engine.process(e)
    st = engine.state
    _, frames = shared_crowd(match_id)
    frame = frames[max(i for i in frames if i <= index)] if any(i <= index for i in frames) else {}
    chances = sum(t.xg for t in st.teams.values())
    return {"match_id": match_id, "home": meta["home"]["name"], "away": meta["away"]["name"],
            "home_id": st.home, "away_id": st.away,
            "home_colour": meta["home"]["colour"], "away_colour": meta["away"]["colour"],
            "score": st.score_str(), "minute": st.minute, "live_minute": minute,
            "quiet": sum(st.score.values()) == 0 and chances < QUIET_XG, "xg": round(chances, 2),
            "scripted": meta.get("scenario") is not None,
            "audience": {"viewers": frame.get("size", 0), "away": frame.get("away", 0),
                         "call_backs": frame.get("alerts_sent", 0)}}


@app.get("/api/live")
def live_matches() -> list[dict[str, Any]]:
    """The matches "live now", at the minute a new viewer joins them, with their audience."""
    return [_live_view(path.stem) for path in sorted(MATCHES_DIR.glob("*.jsonl"))]


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
                 profile: str = "omar", side: str | None = None, lang: str = "en", level: str = "casual",
                 metric: str | None = None, player: str | None = None, speed: int = 10,
                 device: bool = False) -> StreamingResponse:
    """Server-Sent Events: events, snapshots, overlay cues, moment cards, alerts, catch-ups.

    The fan is either configured (``side``/``lang``/``level``/``metric``, the first screen) or a
    preset ``profile`` id. ``device=true`` attaches a fan's phone to an existing session.
    """
    _match_path(match_id)
    session_id = session or uuid.uuid4().hex[:12]
    replay = sessions.get(session_id)
    if device and replay is None:
        raise HTTPException(404, "no such session: scan the QR code shown next to the match")
    if replay is None or replay.match_id != match_id:
        fan = _fan(match_id, side, lang, level, metric, player) if side else _profile(profile, match_id)
        replay = ReplaySession(session_id, match_id, fan, gateway, speed)
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
             "fan": r.fan.profile.display, "fan_present": r.fan.present} for r in sessions.values()]


@app.get("/api/session/{session_id}/live")
async def live_state(session_id: str) -> dict[str, Any]:
    """Current match state of a session: snapshot, danger reasons, verified moment cards."""
    replay = _session(session_id)
    engine = replay.brain.engine
    reasons = {code: tracker.reasons(engine.state.t) for code, tracker in engine.danger.items()}
    cards = [{k: c[k] for k in ("minute", "type", "team", "importance", "headline", "why_it_matters", "source")}
             for c in sorted(replay.brain.cards.values(), key=lambda c: c["t"]) if c["type"] != "danger_peak"]
    return {"snapshot": engine.snapshot(), "danger_reasons": reasons, "moments": cards,
            "fan": replay.fan.profile.display, "fan_present": replay.fan.present}


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


@app.get("/api/session/{session_id}/player/{player}/actions")
async def player_actions(session_id: str, player: str, from_t: float = 0.0,
                         to_t: float | None = None) -> dict[str, Any]:
    """One player's actions between ``from_t`` and ``to_t`` (default: now), for the 2D view of the return screen.

    Coordinates are pitch metres (x 0→105 towards the away goal). A pass is a key pass when its
    receiver shoots within 15 s without the ball changing hands, as in the match engine.
    """
    replay = _session(session_id)
    if player not in replay.brain.engine.state.roster:
        raise HTTPException(404, f"unknown player {player!r}")
    to = replay.brain.engine.state.t if to_t is None else to_t
    actions: list[dict[str, Any]] = []
    open_pass: dict[str, Any] | None = None
    for e in replay.events[: replay.index]:
        if e["t"] > to:
            break
        if e["type"] == "possession_change":
            open_pass = None
        if e["type"] == "shot" and open_pass and e["player"] == open_pass["receiver"] \
                and e["t"] - open_pass["t"] <= KEY_PASS_WINDOW_S:
            open_pass["key"] = True
        if e["t"] < from_t or e.get("player") != player:
            continue
        base = {"type": e["type"], "minute": e["minute"], "x": e["x"], "y": e["y"]}
        if e["type"] == "pass":
            item = {**base, "end_x": e["end_x"], "end_y": e["end_y"], "success": e["success"],
                    "receiver": e["receiver"], "t": e["t"], "key": False}
            actions.append(item)
            open_pass = item if e["success"] else None
        elif e["type"] in ("carry", "sprint"):
            actions.append({**base, "end_x": e["end_x"], "end_y": e["end_y"]})
        elif e["type"] == "shot":
            actions.append({**base, "xg": e["xg"], "outcome": e["outcome"]})
        elif e["type"] in ("tackle", "interception", "pressure"):
            actions.append({**base, "won": bool(e.get("won", e.get("success", True)))})
    for a in actions:
        a.pop("t", None)
        a.pop("receiver", None)
    return {"player": player, "team": replay.brain.engine.state.roster[player]["team"], "actions": actions}


@app.get("/api/session/{session_id}/insights")
async def match_insights(session_id: str, top: int = 6) -> dict[str, Any]:
    """What the engine already knows, for the fan's "Match insights" panel: every shot so far (xG,
    outcome, where) and the players ranked by the same influence score as "What you missed"."""
    from comeback.fans.missed import influence

    replay = _session(session_id)
    st = replay.brain.engine.state
    shots = [{k: e[k] for k in ("minute", "team", "player", "x", "y", "xg", "outcome", "shot_speed_kmh")}
             for e in replay.events[: replay.index] if e["type"] == "shot"]
    ranked = []
    for pid, stats in st.players.items():
        score, reasons = influence(stats)
        if score > 0:
            info = st.roster[pid]
            ranked.append({"id": pid, "name": info["name"], "number": info["number"], "position": info["position"],
                           "team": info["team"], "influence": score, "reasons": reasons, "match": stats.to_dict()})
    ranked.sort(key=lambda p: (-p["influence"], p["id"]))
    return {"t": st.t, "minute": st.minute, "shots": shots, "players": ranked[:top]}


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


@app.post("/api/session/{session_id}/fan")
async def configure_fan(session_id: str, side: str, lang: str = "en", level: str = "casual",
                        metric: str | None = None, player: str | None = None) -> dict[str, Any]:
    """Change the fan's configuration on a running session (same match, same moment)."""
    replay = _session(session_id)
    replay.set_profile(_fan(replay.match_id, side, lang, level, metric, player))
    replay.away_bands = []
    replay.publish("state", replay.state_message())
    return replay.fan.profile.__dict__


@app.post("/api/session/{session_id}/profile")
async def switch_profile(session_id: str, id: str) -> dict[str, Any]:
    replay = _session(session_id)
    replay.set_profile(_profile(id, replay.match_id))
    replay.away_bands = []  # viewing history belongs to the fan, not to the screen
    replay.publish("state", replay.state_message())
    return {"profile": id}
