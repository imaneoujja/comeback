"""The return screen ("what you missed"), the full-time receipt and the "this match got good" rule."""

import asyncio

from fastapi.testclient import TestClient

from comeback.agents.brain import MatchBrain
from comeback.agents.llm import LLMGateway, LLMMode, LLMSettings
from comeback.agents.notes import write_notes
from comeback.agents.watcher import GOOD_QUIET_MIN, Watcher
from comeback.api.replay import ReplaySession
from comeback.api.server import app
from comeback.engine.match import MatchEngine, load_match
from comeback.engine.state import MatchState
from comeback.fans.missed import influence, what_you_missed, window_state
from comeback.fans.profiles import fan_profile
from comeback.fans.receipt import match_receipt
from comeback.fans.session import FanSession

DEMO = "data/matches/demo-comeback.jsonl"
OTHER = "data/matches/random-3112.jsonl"
client = TestClient(app)


def _offline() -> LLMGateway:
    return LLMGateway(LLMSettings(mode=LLMMode.OFFLINE))


def _window(path: str, leave: float | None, back: float, lang: str = "fr") -> tuple[dict, MatchBrain]:
    """The "what you missed" payload of a second-half window, computed the way the replay session does."""
    meta, events = load_match(path)
    brain = MatchBrain(meta, _offline())
    left, start = None, 0.0
    for i, e in enumerate(events):
        brain.process(e)
        m = e["minute"] + e["second"] / 60 if e["period"] == 2 else 0.0
        if leave is not None and left is None and m >= leave:
            left, start = brain.engine.snapshot(), e["t"]
        if m >= back:
            return what_you_missed(meta, events[: i + 1], brain.engine.state, start, e["t"], left,
                                   brain.engine.snapshot(), lang), brain
    raise AssertionError("window not reached")


def test_key_passes_and_duels_are_counted_by_the_engine() -> None:
    meta, _ = load_match(DEMO)
    st = MatchState(meta)
    base = {"match_id": "demo-comeback", "period": 1, "minute": 1, "second": 0, "team": "EMB", "y": 34.0}
    st.apply({**base, "id": "a", "t": 60.0, "type": "pass", "player": "EMB-8", "receiver": "EMB-9", "x": 60.0,
              "end_x": 85.0, "end_y": 30.0, "distance_m": 25.0, "difficulty": 40, "success": True,
              "under_pressure": False, "progressive": True, "ball_speed_kmh": 60.0})
    st.apply({**base, "id": "b", "t": 66.0, "type": "shot", "player": "EMB-9", "x": 88.0, "xg": 0.2,
              "shot_speed_kmh": 90.0, "outcome": "saved", "body_part": "right_foot"})
    st.apply({**base, "id": "c", "t": 70.0, "type": "tackle", "player": "EMB-4", "opponent": "SMC-9", "x": 40.0,
              "won": True})
    assert st.players["EMB-8"].key_passes == 1
    assert (st.players["EMB-4"].duels, st.players["EMB-4"].duels_won) == (1, 1)
    assert (st.players["SMC-9"].duels, st.players["SMC-9"].duels_won) == (1, 0)


def test_what_you_missed_counts_only_the_window_and_ranks_by_influence() -> None:
    missed, brain = _window(DEMO, 63.0, 70.5)
    assert (missed["from_minute"], missed["to_minute"], missed["late_join"]) == (63, 70, False)
    names = [p["name"] for p in missed["players"]]
    assert names[0] == "Ciro Oakenfold" and len(names) == 3
    top = missed["players"][0]
    assert top["window"]["key_passes"] < top["match"]["key_passes"]          # the window is not the match
    scores = [p["influence"] for p in missed["players"]]
    assert scores == sorted(scores, reverse=True)
    emb = missed["teams"]["EMB"]
    assert emb["before"]["score"] == emb["now"]["score"] == "0-2" and emb["window"]["shots"] > 0
    assert "passes clés" in missed["lines"]["EMB-9"] and "0,29 xG" in missed["lines"]["EMB-9"]   # French template
    meta, events = load_match(DEMO)
    whole = window_state(meta, events, 0.0, events[-1]["t"])     # a window covering everything = the engine
    engine = MatchEngine(meta)
    for e in events:
        engine.process(e)
    assert whole.players["EMB-9"].to_dict() == engine.state.players["EMB-9"].to_dict()


def test_volume_is_capped_so_scorers_lead_a_long_window() -> None:
    missed, _ = _window(DEMO, None, 60.0, "en")                 # late join: the story so far
    assert missed["late_join"] and all(t["before"] is None for t in missed["teams"].values())
    assert missed["players"][0]["name"] == "Halen Merewood"     # scored at 18'
    assert missed["players"][0]["reasons"][0] == ("goals", 1)
    stats = MatchBrain(load_match(DEMO)[0], _offline()).engine.state.players["EMB-10"]
    stats.passes_completed, stats.interceptions = 500, 40
    assert influence(stats)[0] == 0.1 * 30 + 1.0 * 5


def test_lines_are_verified_llm_text_only_for_precomputed_windows() -> None:
    precomputed, brain = _window(DEMO, 63.0, 70.5)
    done = asyncio.run(write_notes(precomputed, brain.roster, _offline()))
    assert done["source"] == "llm" and set(done["lines"]) == set(precomputed["lines"])
    other, brain = _window(DEMO, 64.0, 69.0)
    live = LLMGateway(LLMSettings(mode=LLMMode.LIVE, endpoint="https://invalid.example", api_key="x"))
    kept = asyncio.run(write_notes(other, brain.roster, live))      # any other window: no model call per fan
    assert kept["source"] == "template" and kept["lines"] == other["lines"] and live.stats["live_calls"] == 0


def test_the_receipt_counts_live_goals_and_judges_alerts_like_the_readme() -> None:
    async def scenario(path: str, home: str, away: str) -> ReplaySession:
        fan = fan_profile("home", "en", "casual", None, home, away)
        replay = ReplaySession("receipt", path.split("/")[-1][:-6], fan, _offline())
        replay.seek(59)
        replay.schedule(63, 70.5)
        while replay.index < len(replay.events):
            event = replay.events[replay.index]
            replay._process(event)
            replay.index += 1
            await replay._run_plan(event)
        await replay.stop()
        return replay

    demo = asyncio.run(scenario(DEMO, "EMB", "SMC")).receipt()
    assert (demo["goals"], demo["goals_live"], demo["goals_caught_up"]) == (3, 3, 0)   # 71', 84', 92' (from 59')
    assert (demo["alerts"], demo["alerts_came_true"], demo["goals_announced"]) == (2, 1, 1)
    assert demo["minutes_away"] == 7 and demo["minutes_live"] == demo["minutes_followed"] - 7
    assert (demo["chance_horizon_s"], demo["chance_min_xg"], demo["anticipation_min"]) == (90.0, 0.1, 5)
    other = asyncio.run(scenario(OTHER, "AVW", "LKA")).receipt()
    assert other["goals_caught_up"] == 2 and other["goals_live"] == other["goals"] - 2
    events = [{"type": "goal", "t": 100.0, "team": "A"}, {"type": "goal", "t": 500.0, "team": "A"}]
    skipped_one = match_receipt(events, [], [], [(0.0, 200.0)], 900.0)
    assert skipped_one["goals"] == 1 and skipped_one["minutes_followed"] == round(700 / 60)


def test_only_call_me_if_this_match_gets_good() -> None:
    def calls(path: str) -> list[dict]:
        meta, events = load_match(path)
        engine = MatchEngine(meta)
        fan = FanSession(fan_profile("home", "en", "casual", None, meta["home"]["id"], meta["away"]["id"]))
        fan.settings.alert_for = "good"
        watcher = Watcher(fan, engine)
        fan.go_away(0.0)
        out = []
        for e in events:
            for note in watcher.on_update(engine, engine.process(e)):
                if note.kind == "come_back":
                    out.append(note)
                    fan.alerts_this_absence = 0
        return out

    assert calls(DEMO) == []                         # the scripted comeback is never quiet for 8 minutes
    woke = calls(OTHER)
    assert woke and all(n.facts["quiet_minutes"] >= GOOD_QUIET_MIN for n in woke)
    assert "quiet minutes" in woke[0].text


def test_player_actions_for_the_2d_view() -> None:
    from comeback.api import server

    replay = ReplaySession("actions", "demo-comeback", fan_profile("home", "en", "casual", None, "EMB", "SMC"),
                           _offline())
    server.sessions["actions"] = replay
    try:
        replay.seek(75)
        out = client.get("/api/session/actions/player/EMB-8/actions").json()
        assert out["team"] == "EMB" and out["actions"]
        striker = client.get("/api/session/actions/player/EMB-9/actions").json()["actions"]
        assert {"pass", "shot"} <= {a["type"] for a in striker}
        keys = sum(a.get("key", False) for a in out["actions"])
        assert keys == replay.brain.engine.state.players["EMB-8"].key_passes
        assert client.get("/api/session/actions/player/XXX-1/actions").status_code == 404
    finally:
        server.sessions.pop("actions", None)


def test_live_now_and_any_followed_player() -> None:
    """The front door: matches "live now" with their audience; neutral fans and any player to follow."""
    live = {m["match_id"]: m for m in client.get("/api/live").json()}
    assert (live["demo-comeback"]["minute"], live["demo-comeback"]["score"]) == (60, "0-2")
    assert live["random-3112"]["quiet"] and live["random-3112"]["score"] == "0-0"
    assert all(m["audience"]["viewers"] == 10_000 and m["audience"]["call_backs"] > 0 for m in live.values())
    neutral = fan_profile("neutral", "en", "casual", None, "EMB", "SMC")
    assert neutral.club_id is None and neutral.favourite_player_id is None and neutral.pov_team() is None
    follows = fan_profile("home", "fr", "analyst", None, "EMB", "SMC", "EMB-7")
    assert (follows.club_id, follows.favourite_player_id, follows.focus_metric) == ("EMB", "EMB-7", "top_speed")
    assert fan_profile("neutral", "es", "casual", None, "EMB", "SMC", "SMC-9") == \
        fan_profile("player", "es", "casual", None, "EMB", "SMC")       # same texts as the precomputed set-up
    assert fan_profile("home", "en", "casual", None, "EMB", "SMC", "XXX-1").favourite_player_id is None


def test_milestone_cards_say_which_mark_was_reached() -> None:
    from comeback.agents.templates import moment_card_text

    names = {"EMB": "Emberfield", "SMC": "Saltmarsh Comets"}
    base = {"type": "milestone", "minute": 69, "team": "EMB"}
    speed = moment_card_text({**base, "facts": {"milestone": "top_speed_so_far", "player_name": "Ciro Oakenfold",
                                                 "speed_kmh": 34.2, "previous_top_kmh": 33.1}}, names)
    assert "top speed of the match: 34.2 km/h" in speed["headline"] and "33.1" in speed["why_it_matters"]
    fifty = {"milestone": "50_completed_passes", "player_name": "Kiro Sableford"}
    passes = moment_card_text({**base, "facts": fifty}, names)
    assert "50 completed passes" in passes["headline"]
    meta, events = load_match(DEMO)
    engine = MatchEngine(meta)
    for e in events:
        for m in engine.process(e).moments:
            if m.type == "milestone":
                assert "milestone for" not in moment_card_text(m.to_dict(), engine.state.team_names)["headline"].lower()
