"""Tests for the match engine: formulas, danger, state, moments, overlays, alerts."""

from functools import cache
from pathlib import Path

import pytest

from comeback.engine.alerts import AlertRule, AlertTracker
from comeback.engine.danger import Contribution, DangerTracker
from comeback.engine.match import MatchEngine, load_match, run_engine
from comeback.engine.passes import completion_probability, pass_difficulty
from comeback.engine.xg import expected_goals, shot_geometry

DEMO = Path(__file__).resolve().parents[1] / "data" / "matches" / "demo-comeback.jsonl"


@cache
def demo() -> MatchEngine:
    meta, events = load_match(DEMO)
    return run_engine(meta, events)


def demo_events() -> list[dict]:
    return load_match(DEMO)[1]


# ---------------------------------------------------------------- formulas

def test_pass_difficulty_follows_the_spec_formula() -> None:
    assert pass_difficulty(10, False, 0.0, False) == pytest.approx(21.0)
    assert pass_difficulty(40, True, 1.0, True) == 100.0  # clipped
    assert pass_difficulty(20, True, 0.5, False) > pass_difficulty(20, False, 0.5, False)
    assert completion_probability(70, 30) > completion_probability(70, 80)


def test_xg_is_higher_close_and_central_and_lower_for_headers() -> None:
    close = expected_goals(*shot_geometry(97, 34))
    far = expected_goals(*shot_geometry(80, 34))
    wide = expected_goals(*shot_geometry(97, 60))
    assert close > far and close > wide
    assert expected_goals(*shot_geometry(97, 34), header=True) < close
    assert 0.01 <= far <= 0.85 and 0.01 <= close <= 0.85


# ------------------------------------------------------------------ danger

def test_danger_decays_and_reports_its_reasons() -> None:
    tracker = DangerTracker()
    for i in range(5):
        tracker.add(Contribution(100.0 + i, "box_entry", 8.0, "left", f"e{i}"))
    now = tracker.value(105)
    assert 0 < now <= 100
    assert tracker.value(165) < now  # one decay constant later
    assert tracker.slope(105) > 0
    reasons = tracker.reasons(105)
    assert reasons["box_entries"] == 5 and reasons["main_channel"] == "left"


# ------------------------------------------------------------------- state

def test_state_matches_the_raw_events() -> None:
    engine, events = demo(), demo_events()
    st = engine.state
    assert st.score_str() == "3-2" and st.finished
    for code in (st.home, st.away):
        passes = [e for e in events if e["type"] == "pass" and e["team"] == code]
        assert st.teams[code].passes == len(passes)
        assert st.teams[code].passes_completed == sum(e["success"] for e in passes)
    assert st.players_on_pitch == {"EMB": 11, "SMC": 10}
    assert sum(st.possession_share(None).values()) == pytest.approx(1.0)


def test_engine_is_streaming_no_look_ahead() -> None:
    meta, events = load_match(DEMO)
    engine = MatchEngine(meta)
    for event in events:
        engine.process(event)
        if event["minute"] == 64 and event["period"] == 2:
            break
    snap = engine.snapshot()
    assert snap["score_str"] == "0-2"
    assert snap["teams"]["SMC"]["players_on_pitch"] == 10
    assert snap["teams"]["EMB"]["formation"] == "4-2-4"


# ----------------------------------------------------------------- moments

def test_demo_goals_carry_the_storylines() -> None:
    goals = [m for m in demo().moments if m.type == "goal"]
    assert [m.facts["situation"] for m in goals] == [
        "opener", "extends_lead", "pulls_one_back", "equaliser", "go_ahead"]
    first_rovers, equaliser, winner = goals[2], goals[3], goals[4]
    assert first_rovers.facts["missed_big_chance_minute"] == 68
    assert first_rovers.facts["minutes_since_opponent_red_card"] == 8
    assert first_rovers.facts["players_on_pitch"] == {"EMB": 11, "SMC": 10}
    assert equaliser.facts["came_on_minute"] == 55
    assert equaliser.facts["comeback_from_deficit"] == 2
    assert winner.importance >= 95


def test_key_moments_are_detected_with_valid_evidence() -> None:
    engine = demo()
    ids = {e["id"] for e in demo_events()}
    types = {m.type for m in engine.moments}
    assert {"goal", "red_card", "shape_change", "big_chance", "half_time", "full_time",
            "momentum_swing", "danger_peak"} <= types
    red = next(m for m in engine.moments if m.type == "red_card")
    assert red.team == "SMC" and red.facts["players_left"] == 10
    for m in engine.moments:
        assert 0 <= m.importance <= 100
        assert m.evidence_event_ids and set(m.evidence_event_ids) <= ids
    assert len({m.moment_id for m in engine.moments}) == len(engine.moments)


# ---------------------------------------------------------------- overlays

def test_overlay_cues_are_well_formed() -> None:
    engine = demo()
    shots = [e for e in demo_events() if e["type"] == "shot"]
    assert sum(c["template"] == "shot_speed" for c in engine.cues) == len(shots)
    for cue in engine.cues:
        assert cue["layer"] in {"lower_third", "top_right", "banner"}
        assert cue["template"] in {"player_tag", "pass_quality", "shot_speed", "sprint", "distance", "danger", "moment"}
        assert cue["audience"] in {"all", "analyst", "casual"}
        assert cue["t_out"] > cue["t_in"] and 0 <= cue["priority"] <= 100


# ------------------------------------------------------------------ alerts

def test_alert_rule() -> None:
    tracker = AlertTracker(AlertRule(threshold=55, min_slope=3, cooldown_s=180, quiet_after_shot_s=20))
    assert not tracker.check(10, 50, 10, 100)  # below threshold
    assert not tracker.check(10, 60, 0, 100)  # not rising
    assert not tracker.check(10, 60, 10, 5)  # right after own shot
    assert tracker.check(10, 60, 10, 100)
    assert not tracker.check(100, 70, 10, 100)  # cooldown
    assert tracker.check(200, 70, 10, 100)


def test_demo_calls_rovers_fans_back_before_the_71st_minute_goal() -> None:
    meta, events = load_match(DEMO)
    engine, tracker, alerts = MatchEngine(meta), AlertTracker(), []
    for event in events:
        engine.process(event)
        danger, slope = engine.danger_now("EMB")
        if tracker.check(event["t"], danger, slope, engine.state.seconds_since_shot("EMB")):
            alerts.append(event["minute"])
    assert any(66 <= m < 71 for m in alerts)


def test_speed_and_distance_tags_fire_on_thresholds() -> None:
    cues = demo().cues
    sprints = [c for c in cues if c["template"] == "sprint"]
    distances = [c for c in cues if c["template"] == "distance"]
    assert sprints and all(c["data"]["speed_kmh"] >= 32 and c["layer"] == "lower_third" for c in sprints)
    assert distances and all(c["data"]["threshold_m"] % 100 == 0 for c in distances)
    assert all(c["data"]["distance_with_ball_m"] >= c["data"]["threshold_m"] for c in distances)
