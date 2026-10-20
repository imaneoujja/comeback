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


def test_catchup_does_not_drift_while_the_live_feed_moves_on() -> None:
    """The live match keeps running while pending cards are drained: the story is of the moment the fan came back."""
    async def scenario() -> dict:
        replay = ReplaySession("drift", "demo-comeback", load_profiles()["omar"],
                               LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
        replay.subscribe()
        replay.set_paused(True)
        replay.start()
        replay.seek(63)
        replay.go_away()
        replay.seek(70.5)
        drain = replay._drain_cards

        async def drain_while_the_match_goes_on() -> None:
            await drain()
            for event in replay.events[replay.index: replay.index + 60]:   # about a minute of live play
                replay._process(event)
            replay.index += 60

        replay._drain_cards = drain_while_the_match_goes_on
        back = await replay.come_back()
        await replay.stop()
        return back

    back = asyncio.run(scenario())
    assert back["source"] == "llm" and back["delta"]["away_minutes"] == 7


def test_a_scheduled_absence_is_applied_at_exact_minutes() -> None:
    """The guided story plans "away at 63', back at 70.5'": the window must not depend on the browser."""
    async def scenario() -> tuple[list, dict | None]:
        replay = ReplaySession("plan", "demo-comeback", load_profiles()["omar"],
                               LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
        queue = replay.subscribe()
        replay.set_paused(True)
        replay.start()
        replay.seek(59)
        replay.schedule(away=63, back=70.5)
        while replay.index < len(replay.events):
            event = replay.events[replay.index]
            replay._process(event)
            replay.index += 1
            await replay._run_plan(event)
            if event["period"] == 2 and event["minute"] >= 72:
                break
        await replay.stop()
        catchups, calls = [], []
        while not queue.empty():
            message = queue.get_nowait()
            if message["type"] == "catchup":
                catchups.append(message["data"])
            elif message["type"] == "notification" and message["data"]["kind"] == "come_back":
                calls.append(message["data"])
        return replay.away_bands, catchups[0] if catchups else None, calls

    bands, catchup, calls = asyncio.run(scenario())
    # every call-back carries its decision chain and the same moment as the other demo fans get it
    decision = calls[-1]["facts"]["decision"]
    assert decision["relation"] == "attacking" and decision["alert_number"] == 2 and decision["away_for_s"] > 0
    assert calls[-1]["facts"]["danger"] >= decision["threshold"] and decision["slope"] >= decision["min_slope"]
    assert calls[-1]["evidence_event_ids"]
    variants = calls[-1]["variants"]
    assert {v["language"] for v in variants.values()} == {"fr", "en", "es"}
    assert len({v["text"] for v in variants.values()}) == 3
    (band,) = bands
    assert 7 * 60 <= band["to_t"] - band["from_t"] <= 8 * 60          # 63' → 70.5'
    assert catchup and catchup["source"] == "llm" and catchup["audio"] and catchup["delta"]["away_minutes"] == 7


def test_session_endpoints_run_on_the_event_loop() -> None:
    """A plain ``def`` endpoint runs in a worker thread, racing the replay loop (seen as events counted twice)."""
    import inspect

    from fastapi.routing import APIRoute

    session_routes = [r for r in app.routes
                      if isinstance(r, APIRoute) and r.path.startswith(("/api/session", "/api/sessions"))]
    assert session_routes
    assert all(inspect.iscoroutinefunction(r.endpoint) for r in session_routes), \
        [r.path for r in session_routes if not inspect.iscoroutinefunction(r.endpoint)]


def test_the_simulated_audience_is_computed_once_per_match_and_shared() -> None:
    """10,000 fans per viewer would not scale: every session of a match reads the same precomputed frames."""
    from comeback.agents.brain import MatchBrain
    from comeback.engine.match import load_match
    from comeback.fans.crowd import Crowd

    gateway = LLMGateway(LLMSettings(mode=LLMMode.OFFLINE))
    a = ReplaySession("crowd-a", "demo-comeback", load_profiles()["omar"], gateway)
    b = ReplaySession("crowd-b", "demo-comeback", load_profiles()["sofia"], gateway)
    assert a._crowd_frames is b._crowd_frames
    for replay in (a, b):
        while replay.index < len(replay.events):
            replay._process(replay.events[replay.index], silent=True)
            replay.index += 1
    meta, events = load_match("data/matches/demo-comeback.jsonl")
    brain = MatchBrain(meta, gateway)
    reference = Crowd(brain.engine, 10_000)   # the same audience, simulated directly
    for event in events:
        reference.on_event(brain.engine, brain.process(event), brain.cards)
    final = a.crowd_snapshot()
    assert final["grid"] == reference.snapshot(0)["grid"] and final["stories"] == len(reference.story_keys)
    assert final["back_in_time"] == reference.back_in_time and b.crowd_snapshot()["grid"] == final["grid"]


def test_fan_alert_settings_endpoint() -> None:
    from comeback.api import server

    replay = ReplaySession("prefs", "demo-comeback", load_profiles()["omar"],
                           LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
    server.sessions["prefs"] = replay
    try:
        assert replay.state_message()["settings"] == {"alert_for": "threat", "spoilers": False, "night": False}
        out = client.post("/api/session/prefs/settings?alert_for=equaliser&night=true").json()
        assert out == {"alert_for": "equaliser", "spoilers": False, "night": True}
        assert replay.watcher.max_alerts == 1 and replay.watcher.session.settings.night
        assert client.post("/api/session/prefs/settings?alert_for=nonsense").json()["alert_for"] == "equaliser"
    finally:
        server.sessions.pop("prefs", None)


def test_try_another_match_adapts_the_demo_fans_to_the_fixture() -> None:
    listed = {m["match_id"]: m for m in client.get("/api/matches").json()}
    assert listed["demo-comeback"]["scripted"] and not listed["random-3112"]["scripted"]
    fans = {p["id"]: p for p in client.get("/api/profiles?match_id=random-3112").json()}
    match = client.get("/api/match/random-3112").json()
    home, away = match["home"]["id"], match["away"]["id"]
    assert fans["omar"]["club_id"] == home and fans["sofia"]["club_id"] == away
    assert fans["reda"]["favourite_player_id"] == f"{away}-9"
    demo = {p["id"]: p for p in client.get("/api/profiles").json()}
    assert demo["omar"]["club_id"] == "EMB" and demo["reda"]["favourite_player_id"] == "SMC-9"
