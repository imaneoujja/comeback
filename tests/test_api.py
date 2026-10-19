"""Tests for the API and the replay session (no network, offline LLM cache)."""

import asyncio

from fastapi.testclient import TestClient

from comeback.agents.llm import LLMGateway, LLMMode, LLMSettings
from comeback.api.replay import ReplaySession
from comeback.api.server import app
from comeback.fans.profiles import load_profiles

client = TestClient(app)


def test_match_profiles_and_overlays_endpoints() -> None:
    match = client.get("/api/match/demo-comeback").json()
    assert (match["home"]["id"], match["away"]["id"]) == ("RVR", "HLT")
    assert all(p["spot"] for p in match["home"]["players"] if p["id"] in match["home"]["starting_xi"])
    profiles = client.get("/api/profiles").json()
    assert {p["language"] for p in profiles} <= {"en", "fr", "es"}
    casual = client.get("/api/overlays/demo-comeback?profile=sofia").json()
    analyst = client.get("/api/overlays/demo-comeback?profile=omar").json()
    assert 0 < casual["count"] < analyst["count"]
    assert all(c["audience"] in ("all", "casual") for c in casual["cues"])


def test_unknown_resources_are_404() -> None:
    assert client.get("/api/match/nope").status_code == 404
    assert client.get("/api/match/..%2Fprofiles").status_code == 404
    assert client.post("/api/session/nope/away").status_code == 404
    assert client.get("/").status_code == 200


def test_replay_late_join_and_away_back_cycle() -> None:
    async def scenario() -> tuple[dict, dict, list[str]]:
        gateway = LLMGateway(LLMSettings(mode=LLMMode.OFFLINE))
        replay = ReplaySession("test", "demo-comeback", load_profiles()["reda"], gateway)
        queue = replay.subscribe()
        replay.set_paused(True)
        replay.start()  # card writer runs; the clock stays paused
        joined = await replay.join_at(60)
        replay.go_away()
        for event in replay.events[replay.index: replay.index + 400]:
            replay._process(event)
        replay.index += 400
        back = await replay.come_back()
        await replay.stop()
        kinds = []
        while not queue.empty():
            kinds.append(queue.get_nowait()["type"])
        return joined, back, kinds

    joined, back, kinds = asyncio.run(scenario())
    assert joined["late_join"] and joined["bucket"] == "full_story" and joined["language"] == "es"
    assert joined["source"] == "llm"  # precomputed demo window → served from the committed cache
    assert back["bucket"] in ("key_moments", "full_story") and back["text"]
    assert {"state", "catchup", "presence", "event", "snapshot"} <= set(kinds)


def test_phone_pairing_needs_an_existing_session() -> None:
    assert client.get("/phone").status_code == 200
    assert client.get("/api/stream?session=nobody&device=true").status_code == 404
    assert "url" in client.get("/api/lan").json()
