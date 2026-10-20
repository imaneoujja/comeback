"""Tests for the agents: verifier rules, the verified-writing workflow, watcher and catch-ups.

No network: a fake gateway scripts the model replies; the demo test uses the committed cache.
"""

import asyncio
import json
from collections import Counter
from pathlib import Path

from comeback.agents.analyst import AnalystTask, AnalystWriter
from comeback.agents.brain import MatchBrain
from comeback.agents.llm import LLMGateway, LLMMode, LLMSettings, LLMUnavailable
from comeback.agents.verifier import (
    allowed_numbers,
    check_names,
    check_numbers,
    check_numerical_claims,
    check_scope,
)
from comeback.agents.watcher import Watcher
from comeback.agents.workflow import run_verified
from comeback.engine.match import load_match
from comeback.fans.catchup import length_bucket
from comeback.fans.profiles import load_profiles
from comeback.fans.session import FanSession

DEMO = Path(__file__).resolve().parents[1] / "data" / "matches" / "demo-comeback.jsonl"
TEAMS = {"EMB": "Emberfield", "SMC": "Saltmarsh Comets"}
ROSTER = {
    "EMB-9": {"name": "Tavi Kestrel", "team": "EMB"},
    "EMB-7": {"name": "Ivo Farrow", "team": "EMB"},
    "SMC-4": {"name": "Daro Harthill", "team": "SMC"},
}
GOAL = {
    "moment_id": "m001", "t": 4262.0, "minute": 71, "period": 2, "type": "goal", "team": "EMB",
    "players": ["EMB-9"], "importance": 88,
    "facts": {"score_before": "0-2", "score_after": "1-2", "situation": "pulls_one_back", "scorer": "EMB-9",
              "scorer_name": "Tavi Kestrel", "xg": 0.336, "missed_big_chance_minute": 68,
              "players_on_pitch": {"EMB": 11, "SMC": 10}},
    "evidence_event_ids": ["e1"],
}


def task() -> AnalystTask:
    return AnalystTask(GOAL, TEAMS, ROSTER, situation={"players_on_pitch": {TEAMS["EMB"]: 11, TEAMS["SMC"]: 10}})


class FakeGateway:
    """Returns scripted replies in order (an Exception item is raised)."""

    def __init__(self, replies: list) -> None:
        self.replies, self.prompts = list(replies), []

    async def ask(self, agent_name: str, instructions: str, prompt: str):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return type("Reply", (), {"text": reply, "cached": False})()


def card(headline: str, why: str) -> str:
    return json.dumps({"headline": headline, "why_it_matters": why})


GOOD = card("Kestrel makes amends for Emberfield",
            "After his saved chance at 68, Tavi Kestrel cuts it to 1-2 against ten-man Saltmarsh Comets.")


# ---------------------------------------------------------------- verifier

def test_numbers_must_come_from_the_facts() -> None:
    allowed = allowed_numbers(GOAL["facts"], GOAL["minute"])
    assert check_numbers("1-2 at 71 with an xG of 0.34 (34%)", allowed) == []
    assert check_numbers("his 7th goal at 71", allowed)


def test_uninvolved_players_and_foreign_clubs_are_rejected() -> None:
    clubs = {"Emberfield", "Saltmarsh Comets", "Thornwick United"}
    assert check_names("Tavi Kestrel scores", {"EMB-9"}, ROSTER, set(TEAMS.values()), clubs) == []
    assert check_names("Farrow's cross finds Kestrel", {"EMB-9"}, ROSTER, set(TEAMS.values()), clubs)
    assert check_names("like Thornwick United last week", {"EMB-9"}, ROSTER, set(TEAMS.values()), clubs)


def test_numerical_claims_must_name_the_short_handed_team() -> None:
    on_pitch = {"Emberfield": 11, "Saltmarsh Comets": 10}
    assert check_numerical_claims("Saltmarsh Comets are down to 10 men.", on_pitch) == []
    assert check_numerical_claims("Emberfield equalise despite being a man down.", on_pitch)
    assert check_numerical_claims("They play with ten men.", {"A": 11, "B": 11})
    assert check_numerical_claims(
        "Saltmarsh Comets must defend their lead with 10 men against full-strength Emberfield.", on_pitch) == []
    assert check_numerical_claims(
        "Kestrel's goal reignites Emberfield's fight against a ten-man Saltmarsh Comets side.", on_pitch) == []
    assert check_numerical_claims("Kestrel reduces Saltmarsh Comets's lead, boosting Emberfield' momentum "
                                  "despite playing with a numerical disadvantage.", on_pitch)
    assert check_numerical_claims("Emberfield win, overcoming a numerical advantage for Saltmarsh Comets.",
                                  on_pitch)
    assert check_numerical_claims("Emberfield, with a numerical advantage, keep pushing.", on_pitch) == []
    assert check_numerical_claims("Emberfield win, overcoming a numerical advantage after Saltmarsh Comets "
                                  "lost a player.", on_pitch)
    assert check_numerical_claims("An early lead with both teams at full strength.", {"A": 11, "B": 11}) == []
    fr = {"Emberfield": 11, "Saltmarsh Comets": 10}
    assert check_numerical_claims(
        "Une gestion tactique d’Emberfield face à l’infériorité numérique des Saltmarsh Comets.", fr) == []


def test_claims_must_stay_within_the_match() -> None:
    assert check_scope("the fastest shot of the season")
    assert check_scope("el tiro más rápido de la temporada")
    assert check_scope("the fastest shot of the match") == []


# ---------------------------------------------------------------- workflow

def run(gateway: FakeGateway):
    return asyncio.run(run_verified(AnalystWriter(), task(), gateway))


def test_good_draft_passes_first_time() -> None:
    result = run(FakeGateway([GOOD]))
    assert (result.source, result.attempts, result.verified) == ("llm", 1, True)


def test_rejected_draft_is_retried_with_precise_feedback() -> None:
    bad = card("Kestrel scores his 9th", "A 1-2 that changes everything.")
    gateway = FakeGateway([bad, GOOD])
    result = run(gateway)
    assert (result.source, result.attempts) == ("llm", 2)
    assert "fix_these_problems_from_your_previous_draft" in gateway.prompts[1]
    assert "9" in result.rejections[0][0]


def test_gives_up_after_three_rejections_and_uses_the_template() -> None:
    bad = card("Kestrel scores his 9th", "A 1-2 that changes everything.")
    result = run(FakeGateway([bad, bad, bad]))
    assert (result.source, result.attempts, len(result.rejections)) == ("template", 3, 3)
    assert "Tavi Kestrel" in result.output["headline"]


def test_llm_failure_and_invalid_json_are_recovered() -> None:
    assert run(FakeGateway([LLMUnavailable("429 rate limited")])).source == "template"
    result = run(FakeGateway(["Sure! Here is the card.", GOOD]))
    assert (result.source, result.attempts) == ("llm", 2)


def test_offline_gateway_never_calls_the_network(tmp_path: Path) -> None:
    gateway = LLMGateway(LLMSettings(mode=LLMMode.OFFLINE, cache_path=tmp_path / "c.jsonl",
                                     budget_path=tmp_path / "b.json"))
    result = asyncio.run(run_verified(AnalystWriter(), task(), gateway))
    assert result.source == "template" and gateway.stats["offline_misses"] == 1


# -------------------------------------------------------- demo end to end

def test_demo_runs_offline_with_verified_llm_cards_from_the_committed_cache() -> None:
    meta, events = load_match(DEMO)
    brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))

    async def replay() -> None:
        for event in events:
            for moment in brain.process(event).moments:
                if brain.cards[moment.moment_id]["pending"]:
                    await brain.write_card(moment)

    asyncio.run(replay())
    sources = Counter(c["source"] for c in brain.cards.values() if c["importance"] >= 50
                      and c["type"] != "danger_peak")
    assert sources["llm"] >= 15 and sources["template"] == 0
    assert all(c["verified"] for c in brain.cards.values())


# ------------------------------------------------------- watcher, catch-up

def test_watcher_calls_omar_back_before_the_goal_and_respects_presence() -> None:
    meta, events = load_match(DEMO)
    brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
    profiles = load_profiles()
    omar, sofia = FanSession(profiles["omar"]), FanSession(profiles["sofia"])
    watchers = [Watcher(omar, brain.engine), Watcher(sofia, brain.engine)]
    notes = []
    for event in events:
        update = brain.process(event)
        if event["period"] == 2 and event["minute"] == 65:
            omar.go_away(event["t"])
        if event["period"] == 2 and event["minute"] >= 72:
            break
        for watcher in watchers:
            notes += [(watcher.session.profile.id, n) for n in watcher.on_update(brain.engine, update)]
    omar_notes = [n for fan, n in notes if fan == "omar"]
    assert not [n for fan, n in notes if fan == "sofia"]  # Sofia never left
    come_backs = [n for n in omar_notes if n.kind == "come_back"]
    assert come_backs and come_backs[0].minute < 71 and come_backs[0].text.startswith("Reviens")
    assert len(come_backs) <= 2
    assert any(n.kind == "goal" and n.minute == 71 for n in omar_notes)


def test_catchup_length_adapts_to_the_absence() -> None:
    assert length_bucket(120) == "line"
    assert length_bucket(600) == "key_moments"
    assert length_bucket(1500) == "full_story"
    assert length_bucket(30, late_join=True) == "full_story"


def test_workflow_traces_each_step_for_the_control_room() -> None:
    bad = card("Kestrel scores his 9th", "A 1-2 that changes everything.")
    steps = []
    asyncio.run(run_verified(AnalystWriter(), task(), FakeGateway([bad, GOOD]), steps.append))
    assert [(s["agent"], s["step"]) for s in steps] == [
        ("Analyst", "draft"), ("Verifier", "rejected"), ("Analyst", "draft"), ("Verifier", "verified")]
    assert "9" in steps[1]["detail"] and steps[0]["label"] == "71' goal"


def test_a_crowd_of_fans_needs_few_stories() -> None:
    from comeback.fans.crowd import Crowd

    meta, events = load_match(DEMO)
    brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
    crowd = Crowd(brain.engine, size=2000)
    for event in events:
        update = brain.process(event)
        crowd.on_event(brain.engine, update, brain.cards)
    snap = crowd.snapshot(analyst_calls=17)
    assert snap["catchups"] > 1000 and snap["alerts_sent"] > 0
    assert snap["stories"] < snap["catchups"] / 5          # most catch-ups reuse an already written story
    assert [g["minute"] for g in snap["back_in_time"]] == [18, 39, 71, 84, 92]
    assert len(snap["grid"]) == 2000


def test_every_fans_last_alert_before_a_goal_names_the_scoring_side(monkeypatch) -> None:
    """Demo coherence: whatever the fan, the call-back before a goal is about the team that then scores."""
    import comeback.agents.watcher as watcher_module

    monkeypatch.setattr(watcher_module, "MAX_ALERTS_PER_ABSENCE", 99)
    meta, events = load_match(DEMO)
    for fan_id, profile in load_profiles().items():
        brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
        session = FanSession(profile)
        session.go_away(0.0)                       # away for the whole match: sees every alert
        watcher = Watcher(session, brain.engine)
        alerts, goals = [], []
        for event in events:
            for note in watcher.on_update(brain.engine, brain.process(event)):
                if note.kind == "come_back":
                    alerts.append(note)
            if event["type"] == "goal":
                goals.append(event)
        for goal in goals:
            before = [a for a in alerts if goal["t"] - 360 <= a.t < goal["t"]]
            assert before, (fan_id, goal["minute"], "no call-back before the goal")
            assert before[-1].team == goal["team"], (fan_id, goal["minute"], before[-1].text)


def test_every_fan_gets_a_verified_full_time_gazette() -> None:
    meta, events = load_match(DEMO)
    brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))

    async def replay() -> list[dict]:
        for event in events:
            for moment in brain.process(event).moments:
                if brain.cards[moment.moment_id]["pending"]:
                    await brain.write_card(moment)
        return [await brain.final_recap(p) for p in load_profiles().values()]

    recaps = asyncio.run(replay())
    assert {r["language"] for r in recaps} == {"en", "fr", "es"}
    for recap in recaps:
        assert recap["final"] and recap["source"] == "llm" and recap["headline"]
        assert 0 < len(recap["key_moments"]) <= 6


def test_called_it_only_after_a_real_alert_for_the_scorer_within_five_minutes() -> None:
    """The "called it" receipt is a claim about our own alert: it must never be shown without one."""
    meta, _ = load_match(DEMO)
    engine = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE))).engine
    goal = {"type": "goal", "team": "EMB", "t": 4280.0, "minute": 71, "id": "e1"}

    def receipt(alerts: list[dict]) -> object:
        session = FanSession(load_profiles()["omar"])   # present: the fan is back in time
        session.notifications = alerts
        return Watcher(session, engine)._called_it(goal)

    alert = {"kind": "come_back", "team": "EMB", "t": 4160.0, "minute": 69}
    assert receipt([]) is None                                                  # no alert at all
    assert receipt([{**alert, "team": "SMC"}]) is None                          # alert about the other team
    assert receipt([{**alert, "t": 3970.0, "minute": 66}]) is None              # older than the 5-minute window
    assert receipt([{**alert, "kind": "goal"}]) is None                         # a goal notification is not an alert
    assert receipt([{**alert, "t": 4290.0}]) is None                            # an alert after the goal
    note = receipt([alert])
    assert note.kind == "called_it" and note.facts == {"alert_minute": 69, "goal_minute": 71, "lead_s": 120,
                                                       "score": engine.state.score_str()}


def test_called_it_is_never_sent_while_the_fan_is_still_away() -> None:
    """Away at the goal means the fan missed it: a goal notification, not a receipt."""
    meta, events = load_match(DEMO)
    brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
    omar = FanSession(load_profiles()["omar"])
    watcher = Watcher(omar, brain.engine)
    kinds = []
    for event in events:
        update = brain.process(event)
        if event["period"] == 2 and event["minute"] == 63 and omar.present:
            omar.go_away(event["t"])
        if event["period"] == 2 and event["minute"] >= 72:
            break
        kinds += [n.kind for n in watcher.on_update(brain.engine, update)]
    assert "come_back" in kinds and "goal" in kinds and "called_it" not in kinds
