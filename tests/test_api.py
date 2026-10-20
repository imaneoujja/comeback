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
    assert (match["home"]["id"], match["away"]["id"]) == ("EMB", "SMC")
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
    assert joined["audio"] and joined["audio"].startswith("/media/audio/")   # committed neural voice
    assert 0 < len(joined["replay"]) <= 3 and all(clip["events"] for clip in joined["replay"])
    assert client.get(joined["audio"]).status_code == 200
    assert back["bucket"] in ("key_moments", "full_story") and back["text"]
    assert {"state", "catchup", "presence", "event", "snapshot"} <= set(kinds)


def test_live_state_endpoints_for_mcp() -> None:
    from comeback.api import server

    replay = ReplaySession("mcp", "demo-comeback", load_profiles()["omar"],
                           LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
    for event in replay.events[:600]:
        replay.brain.process(event)
    server.sessions["mcp"] = replay
    try:
        assert any(s["session"] == "mcp" for s in client.get("/api/sessions").json())
        live = client.get("/api/session/mcp/live").json()
        assert {"snapshot", "danger_reasons", "moments"} <= live.keys()
        assert client.get("/api/session/mcp/player/EMB-9").json()["id"] == "EMB-9"
        assert client.get("/api/session/mcp/player/nobody").status_code == 404
    finally:
        server.sessions.pop("mcp", None)


def test_phone_pairing_needs_an_existing_session() -> None:
    assert client.get("/phone").status_code == 200
    assert client.get("/api/stream?session=nobody&device=true").status_code == 404
    assert "url" in client.get("/api/lan").json()


def test_guided_story_seek_then_away_and_back_hits_the_cache() -> None:
    """The guided story: Omar watches from 59', leaves at 63', is called back twice, returns at 70.5'."""
    async def scenario() -> tuple[list[dict], dict, list[str]]:
        gateway = LLMGateway(LLMSettings(mode=LLMMode.OFFLINE))
        replay = ReplaySession("story", "demo-comeback", load_profiles()["omar"], gateway)
        queue = replay.subscribe()
        replay.set_paused(True)
        replay.start()
        replay.seek(59)
        assert replay.fan.present and not replay.away_bands

        def play_until(minute: float) -> None:  # up to and including the first event at ``minute``
            while True:
                event = replay.events[replay.index]
                replay._process(event)
                replay.index += 1
                if event["period"] == 2 and event["minute"] + event["second"] / 60 >= minute:
                    return

        play_until(63)
        replay.go_away()
        play_until(70.5)
        back = await replay.come_back()
        play_until(71.4)  # the 71' goal (71:20), seen live
        await replay.stop()
        kinds = []
        while not queue.empty():
            kinds.append(queue.get_nowait()["type"])
        return replay.fan.notifications, back, kinds

    notes, back, kinds = asyncio.run(scenario())
    calls = [n for n in notes if n["kind"] == "come_back"]
    assert [n["minute"] for n in calls] == [65, 69] and all(n["team"] == "EMB" for n in calls)
    assert back["source"] == "llm" and back["audio"] and back["replay"]
    assert "catchup" in kinds
    receipt = [n for n in notes if n["kind"] == "called_it"]
    assert len(receipt) == 1 and receipt[0]["facts"]["alert_minute"] == 69 and receipt[0]["minute"] == 71
    assert "69" in receipt[0]["text"]  # French: "alerte à la 69e, but à la 71e"


def test_failure_drill_falls_back_to_verified_templates() -> None:
    """Cutting the LLM for one session: moment cards and catch-ups still arrive, flagged as templates."""
    async def scenario() -> tuple[list[dict], dict, list[dict]]:
        gateway = LLMGateway(LLMSettings(mode=LLMMode.OFFLINE))
        replay = ReplaySession("drill", "demo-comeback", load_profiles()["sofia"], gateway)
        queue = replay.subscribe()
        replay.set_paused(True)
        replay.start()
        replay.set_outage(True)
        joined = await replay.join_at(30)
        await replay.stop()
        messages = []
        while not queue.empty():
            messages.append(queue.get_nowait())
        return list(replay.brain.cards.values()), joined, messages

    cards, joined, messages = asyncio.run(scenario())
    assert cards and all(c["source"] == "template" for c in cards if not c["pending"])
    assert joined["source"] == "template" and joined["text"]
    assert {"type": "outage", "data": {"down": True}} in messages
    assert any(m["type"] == "agent" and m["data"]["step"] == "unavailable" for m in messages)
