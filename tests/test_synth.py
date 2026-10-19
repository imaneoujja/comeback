"""Tests for the synthetic match generator: realism, schema, determinism, demo script."""

import statistics
from functools import cache
from typing import Any

import pytest

from comeback.synth.cli import generate_random, generate_scenario
from comeback.synth.teams import CLUBS, build_fixture

N_MATCHES = 20
COMMON_FIELDS = {"id", "match_id", "t", "period", "minute", "second", "type", "team", "player"}


@cache
def random_matches() -> tuple[tuple[dict[str, Any], ...], ...]:
    return tuple(tuple(generate_random(seed)) for seed in range(1, N_MATCHES + 1))


@cache
def demo_match() -> tuple[dict[str, Any], ...]:
    return tuple(generate_scenario("demo-comeback"))


def _of_type(events, etype: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == etype]


def match_stats(records) -> dict[str, float]:
    meta, events = records[0], records[1:]
    passes = _of_type(events, "pass")
    shots = _of_type(events, "shot")
    home_passes = sum(e["team"] == meta["home"]["id"] for e in passes)
    return {
        "passes": len(passes),
        "accuracy": sum(e["success"] for e in passes) / len(passes),
        "shots": len(shots),
        "xg": sum(e["xg"] for e in shots),
        "goals": len(_of_type(events, "goal")),
        "home_possession": home_passes / len(passes),
    }


# ----------------------------------------------------------------- realism

@pytest.mark.parametrize(
    ("stat", "low", "high"),
    [
        ("passes", 800, 1100),
        ("accuracy", 0.75, 0.88),
        ("shots", 18, 32),
        ("xg", 1.8, 3.8),
        ("goals", 2.0, 3.4),
        ("home_possession", 0.35, 0.65),
    ],
)
def test_average_stats_are_realistic(stat: str, low: float, high: float) -> None:
    values = [match_stats(m)[stat] for m in random_matches()]
    assert low <= statistics.mean(values) <= high


@pytest.mark.parametrize(
    ("stat", "low", "high"),
    [("passes", 700, 1200), ("accuracy", 0.70, 0.90), ("home_possession", 0.30, 0.70)],
)
def test_every_match_is_plausible(stat: str, low: float, high: float) -> None:
    for m in random_matches():
        assert low <= match_stats(m)[stat] <= high, (m[0]["match_id"], stat)


# ------------------------------------------------------------------ schema

def test_event_schema_and_ordering() -> None:
    for records in (*random_matches()[:3], demo_match()):
        meta, events = records[0], records[1:]
        assert meta["type"] == "match_start"
        assert len({e["id"] for e in events}) == len(events)
        ts = [e["t"] for e in events]
        assert ts == sorted(ts)
        for e in events:
            assert e.keys() >= COMMON_FIELDS
            if "x" in e:
                assert 0 <= e["x"] <= 105 and 0 <= e["y"] <= 68
            if e["type"] == "pass":
                assert 0 <= e["difficulty"] <= 100
            if e["type"] == "shot":
                assert 0.01 <= e["xg"] <= 0.85 or e["body_part"] == "penalty"
                assert 55 <= e["shot_speed_kmh"] <= 125
            if e["type"] == "sprint":
                assert e["speed_kmh"] > 30
        assert events[-1]["type"] == "match_end"


def test_goal_events_keep_the_score() -> None:
    for records in random_matches():
        meta, events = records[0], records[1:]
        home = away = 0
        for goal in _of_type(events, "goal"):
            home += goal["team"] == meta["home"]["id"]
            away += goal["team"] == meta["away"]["id"]
            assert (goal["score_home"], goal["score_away"]) == (home, away)
        assert (events[-1]["score_home"], events[-1]["score_away"]) == (home, away)


def test_players_in_events_belong_to_the_rosters() -> None:
    meta, events = demo_match()[0], demo_match()[1:]
    roster = {p["id"] for side in ("home", "away") for p in side_players(meta, side)}
    for e in events:
        for key in ("player", "receiver", "scorer", "assist", "target_player", "opponent"):
            if e.get(key):
                assert e[key] in roster, (e["id"], key)


def side_players(meta: dict[str, Any], side: str) -> list[dict[str, Any]]:
    return meta[side]["players"]


# ------------------------------------------------------------- determinism

def test_generation_is_deterministic() -> None:
    assert generate_random(7) == generate_random(7)
    assert generate_random(7) != generate_random(8)


def test_player_names_are_unique_within_a_match() -> None:
    for seed in range(200):
        home, away = build_fixture("RVR", "HLT", seed)
        names = [p.name for p in home.players + away.players]
        assert len(names) == len(set(names))


def test_clubs_are_fictional_and_complete() -> None:
    assert set(CLUBS) == {"RVR", "HLT", "NRA", "ELM", "CPC", "SVW"}


# ---------------------------------------------------------------- the demo

def test_demo_follows_the_comeback_script() -> None:
    events = demo_match()[1:]
    goals = [(e["minute"], e["team"], e["scorer"], e["score_home"], e["score_away"])
             for e in _of_type(events, "goal")]
    assert goals == [
        (18, "HLT", "HLT-9", 0, 1),
        (39, "HLT", "HLT-11", 0, 2),
        (71, "RVR", "RVR-9", 1, 2),
        (84, "RVR", "RVR-15", 2, 2),
        (92, "RVR", "RVR-10", 3, 2),
    ]
    reds = [e for e in _of_type(events, "card") if e["color"] == "red"]
    assert [(e["minute"], e["player"]) for e in reds] == [(62, "HLT-4")]
    shape = [e for e in _of_type(events, "substitution") if e.get("formation")]
    assert [(e["minute"], e["player_in"], e["formation"]) for e in shape] == [(55, "RVR-15", "4-2-4")]
    missed = [e for e in _of_type(events, "shot") if e["player"] == "RVR-9" and e["minute"] == 68]
    assert missed and missed[0]["outcome"] == "saved" and missed[0]["xg"] >= 0.2
