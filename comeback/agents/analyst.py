"""Analyst agent: turns a detected moment into a verified Moment Card (English, neutral).

It receives compact computed facts (never the raw event log) and writes a headline
plus "why it matters". The card is written once per moment and shared by every
fan; language, level and point of view are adapted later by the Storyteller.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from comeback.agents.llm import LLMGateway, parse_json_reply
from comeback.agents.templates import moment_card_text
from comeback.agents.verifier import (
    allowed_numbers,
    check_length,
    check_names,
    check_no_final_result,
    check_numbers,
    check_numerical_claims,
    check_scope,
)
from comeback.agents.workflow import Tracer, WrittenResult, run_verified
from comeback.synth.teams import CLUBS

ANALYST_MIN_IMPORTANCE = 50
SKIP_TYPES = {"danger_peak"}  # transient; described live by the danger overlay and the Watcher
HEADLINE_MAX = 90
WHY_MAX = 320

ANALYST_INSTRUCTIONS = """You are the Analyst of a football broadcast studio. The match and all its
clubs and players are fictional. You receive the computed facts of one key moment and
the current match situation (score, players on the pitch per team).
Write JSON only: {"headline": "...", "why_it_matters": "..."}.
- headline: max 12 words, sentence case, present tense, vivid but factual; do not
  put the minute in the headline.
- why_it_matters: 1-2 sentences (max 45 words) explaining WHY the moment matters, not
  just that it happened: score situation, momentum/control, numerical advantage,
  storylines given in the facts (redemption after a missed chance, a substitute's
  impact, a comeback).
- Use ONLY names and numbers that appear in the input. Never invent events, players,
  statistics or quotes. Do not mention real clubs, leagues, players or brands.
- Check "players_on_pitch" before mentioning a numerical advantage: the team with
  fewer players is the one that had a player sent off.
- Neutral tone, English."""


@dataclass
class AnalystTask:
    """One moment to write up, with light match context."""

    moment: dict[str, Any]
    team_names: dict[str, str]
    roster: dict[str, dict[str, Any]]
    recent_headlines: list[str] = field(default_factory=list)
    situation: dict[str, Any] = field(default_factory=dict)


def readable_facts(facts: dict[str, Any], team_names: dict[str, str]) -> dict[str, Any]:
    """Facts for a prompt: no raw player ids (``*_name`` fields carry names), team codes → names."""
    id_keys = {k[: -len("_name")] for k in facts if k.endswith("_name")}

    def named(value: Any) -> Any:
        if isinstance(value, dict):
            return {team_names.get(k, k): named(v) for k, v in value.items()}
        if isinstance(value, list):
            return [named(v) for v in value]
        return team_names.get(value, value) if isinstance(value, str) else value

    return {k: named(v) for k, v in facts.items() if k not in id_keys}


def moment_player_ids(moment: dict[str, Any]) -> set[str]:
    """Players a text about this moment may name."""
    ids = set(moment.get("players", []))
    ids |= {v for k, v in moment["facts"].items()
            if isinstance(v, str) and not k.endswith("_name") and "-" in v and v.split("-")[0].isupper()}
    return ids


class AnalystWriter:
    """VerifiedWriter implementation for moment cards."""

    agent_name = "Analyst"
    instructions = ANALYST_INSTRUCTIONS

    def label(self, task: AnalystTask) -> str:
        return f"{task.moment['minute']}' {task.moment['type'].replace('_', ' ')}"

    def prompt(self, task: AnalystTask, feedback: list[str]) -> str:
        m = task.moment
        payload: dict[str, Any] = {
            "moment": {"type": m["type"], "minute": m["minute"], "team": task.team_names.get(m["team"]),
                       "importance": m["importance"]},
            "teams": list(task.team_names.values()),
            "situation": task.situation,
            "facts": readable_facts(m["facts"], task.team_names),
            "earlier_headlines": task.recent_headlines[-4:],
        }
        if feedback:
            payload["fix_these_problems_from_your_previous_draft"] = feedback
        return json.dumps(payload, ensure_ascii=False)

    def parse(self, text: str) -> dict[str, Any]:
        data = parse_json_reply(text)
        return {"headline": str(data["headline"]).strip(), "why_it_matters": str(data["why_it_matters"]).strip()}

    def verify(self, task: AnalystTask, output: dict[str, Any]) -> list[str]:
        m = task.moment
        text = f"{output.get('headline', '')}\n{output.get('why_it_matters', '')}"
        allowed = allowed_numbers(m["facts"], m["minute"], task.recent_headlines, task.situation)
        issues = check_length(output.get("headline", ""), HEADLINE_MAX, "headline")
        issues += check_length(output.get("why_it_matters", ""), WHY_MAX, "why_it_matters")
        issues += check_numbers(text, allowed)
        issues += check_names(text, moment_player_ids(m), task.roster,
                              set(task.team_names.values()), {c.name for c in CLUBS.values()})
        issues += check_numerical_claims(text, task.situation.get("players_on_pitch", {}))
        issues += check_scope(text)
        issues += check_no_final_result(text, m["type"] == "full_time")
        return issues

    def fallback(self, task: AnalystTask) -> dict[str, Any]:
        return moment_card_text(task.moment, task.team_names)


def needs_analyst(moment: dict[str, Any]) -> bool:
    """Only important moments are worth an LLM call; the rest get template cards."""
    return moment["importance"] >= ANALYST_MIN_IMPORTANCE and moment["type"] not in SKIP_TYPES


def to_card(moment: dict[str, Any], result: WrittenResult) -> dict[str, Any]:
    """Moment Card: the moment, its verified text and provenance."""
    return {
        **moment,
        "headline": result.output["headline"],
        "why_it_matters": result.output["why_it_matters"],
        "verified": result.verified,
        "source": result.source,
        "attempts": result.attempts,
        "fallback_reason": result.fallback_reason,
    }


async def write_moment_card(task: AnalystTask, gateway: LLMGateway, trace: Tracer | None = None) -> dict[str, Any]:
    """Moment Card via Analyst → Verifier workflow (or a direct template for minor moments)."""
    if not needs_analyst(task.moment):
        result = WrittenResult(moment_card_text(task.moment, task.team_names), "template", True, 0, [],
                               "minor moment: no LLM call")
    else:
        result = await run_verified(AnalystWriter(), task, gateway, trace)
    return to_card(task.moment, result)
