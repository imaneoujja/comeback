"""MCP server: lets any agent (e.g. GitHub Copilot in VS Code) query a live COMEBACK match.

It reads a running COMEBACK server over HTTP (local or the public deployment), so
an assistant can ask "who is dangerous right now?" or "what did I miss since 60'?".

Usage (stdio transport):
    pip install -r requirements-extras.txt
    COMEBACK_URL=http://localhost:8000 python -m comeback.mcp_server
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.getenv("COMEBACK_URL", "http://localhost:8000").rstrip("/")

mcp = FastMCP(
    "comeback",
    instructions="Live state of a synthetic football match followed by COMEBACK: score, danger index, "
                 "verified key moments and player stats. Clubs and players are fictional.",
)


def _get(path: str) -> Any:
    response = httpx.get(f"{BASE_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def _session(session_id: str | None) -> str:
    if session_id:
        return session_id
    live = _get("/api/sessions")
    if not live:
        raise ValueError("No live match: open COMEBACK in a browser first.")
    return max(live, key=lambda s: (s["period"], s["minute"]))["session"]


@mcp.tool()
def live_sessions() -> list[dict[str, Any]]:
    """List the matches currently being watched (session id, minute, score, fan)."""
    return _get("/api/sessions")


@mcp.tool()
def match_state(session_id: str | None = None) -> dict[str, Any]:
    """Score, clock, possession, shots, xG and players on the pitch of the live match."""
    snap = _get(f"/api/session/{_session(session_id)}/live")["snapshot"]
    teams = {code: {k: t[k] for k in ("name", "shots", "xg", "possession", "possession_5min", "pass_accuracy",
                                      "players_on_pitch", "formation", "danger")}
             for code, t in snap["teams"].items()}
    return {"minute": snap["minute"], "period": snap["period"], "score": snap["score_str"], "teams": teams}


@mcp.tool()
def danger_now(session_id: str | None = None) -> dict[str, Any]:
    """Which team is dangerous right now, and why (box entries, shots, corners over the last 2 minutes)."""
    live = _get(f"/api/session/{_session(session_id)}/live")
    return {code: {"danger": live["snapshot"]["teams"][code]["danger"],
                   "rising": live["snapshot"]["teams"][code]["danger_slope"] > 0,
                   **{k: v for k, v in reasons.items() if k != "evidence_event_ids"}}
            for code, reasons in live["danger_reasons"].items()}


@mcp.tool()
def key_moments(since_minute: int = 0, session_id: str | None = None) -> list[dict[str, Any]]:
    """Verified key moments (written by the Analyst agent, checked by the Verifier) since a minute."""
    moments = _get(f"/api/session/{_session(session_id)}/live")["moments"]
    return [m for m in moments if m["minute"] >= since_minute]


@mcp.tool()
def player_stats(player: str, session_id: str | None = None) -> dict[str, Any]:
    """Live stats of a player, by id (e.g. "EMB-9") or name (e.g. "Oakenfold")."""
    return _get(f"/api/session/{_session(session_id)}/player/{player}")


if __name__ == "__main__":
    mcp.run()
