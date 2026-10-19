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
from comeback.api.replay import MATCHES_DIR, SPEEDS, ReplaySession, cue_visible
from comeback.engine.match import load_match, run_engine
from comeback.fans.crowd import scaling_curve
from comeback.fans.profiles import load_profiles

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
DEFAULT_MATCH = "demo-comeback"
KEEPALIVE_S = 15.0

sessions: dict[str, ReplaySession] = {}
gateway = LLMGateway()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    for session in sessions.values():
        await session.stop()


app = FastAPI(title="COMEBACK", description="The AI that watches the match for you while you're away.",
              lifespan=lifespan)
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def _match_path(match_id: str) -> Path:
    path = MATCHES_DIR / f"{match_id}.jsonl"
    if not path.is_file() or path.parent != MATCHES_DIR:
        raise HTTPException(404, f"unknown match {match_id!r}")
    return path


def _session(session_id: str) -> ReplaySession:
    if session_id not in sessions:
        raise HTTPException(404, "unknown session: open the stream first")
    return sessions[session_id]


def _profile(profile_id: str):
    profiles = load_profiles()
    if profile_id not in profiles:
        raise HTTPException(404, f"unknown profile {profile_id!r}")
    return profiles[profile_id]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/phone", include_in_schema=False)
def phone_page() -> FileResponse:
    """The fan's real phone: pairs with a control-room session through a QR code."""
    return FileResponse(WEB_DIR / "phone.html")


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


@app.get("/api/profiles")
def profiles() -> list[dict[str, Any]]:
    return [p.__dict__ for p in load_profiles().values()]


@cache
def _overlays(match_id: str) -> list[dict[str, Any]]:
    meta, events = load_match(_match_path(match_id))
    return run_engine(meta, events).cues


@app.get("/api/overlays/{match_id}")
def overlays(match_id: str, profile: str | None = None) -> dict[str, Any]:
    """Timed, renderer-agnostic overlay cues for the whole match (optionally for one profile's level)."""
    cues = _overlays(match_id)
    if profile:
        level = _profile(profile).level
        cues = [c for c in cues if cue_visible(c, level)]
    return {"match_id": match_id, "count": len(cues), "cues": cues}


_scale_cache: dict[str, list[dict[str, int]]] = {}


@app.get("/api/scale/{match_id}")
async def scale(match_id: str) -> dict[str, Any]:
    """LLM calls needed to serve audiences of growing size (computed once, in a worker thread)."""
    if match_id not in _scale_cache:
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
        replay = ReplaySession(session_id, match_id, _profile(profile), gateway, speed)
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

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.post("/api/session/{session_id}/away")
def away(session_id: str) -> dict[str, Any]:
    return _session(session_id).go_away()


@app.post("/api/session/{session_id}/back")
async def back(session_id: str) -> JSONResponse:
    catchup = await _session(session_id).come_back()
    return JSONResponse(catchup or {"message": "already present"})


@app.post("/api/session/{session_id}/join")
async def join(session_id: str, minute: float = 60) -> dict[str, Any]:
    return await _session(session_id).join_at(minute)


@app.post("/api/session/{session_id}/speed")
def set_speed(session_id: str, value: int) -> dict[str, Any]:
    if value not in SPEEDS:
        raise HTTPException(400, f"speed must be one of {SPEEDS}")
    _session(session_id).set_speed(value)
    return {"speed": value}


@app.post("/api/session/{session_id}/pause")
def pause(session_id: str, paused: bool = True) -> dict[str, Any]:
    _session(session_id).set_paused(paused)
    return {"paused": paused}


@app.post("/api/session/{session_id}/profile")
def switch_profile(session_id: str, id: str) -> dict[str, Any]:
    replay = _session(session_id)
    replay.set_profile(_profile(id))
    replay.away_bands = []  # viewing history belongs to the fan, not to the screen
    replay.publish("state", replay.state_message())
    return {"profile": id}
