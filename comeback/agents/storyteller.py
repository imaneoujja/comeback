"""Storyteller agent: a personalised "previously on…" catch-up for a returning fan.

Input: the verified Moment Cards of the away window, a delta block (what changed)
and the fan profile. Output: text in the fan's language, level and point of view,
sized to the absence. Goes through the same Writer → Verifier → fallback workflow.
"""

import json
from dataclasses import dataclass
from typing import Any

from comeback.agents.analyst import moment_player_ids, readable_facts
from comeback.agents.llm import LLMGateway, parse_json_reply
from comeback.agents.templates import CATCHUP_INTRO, NOTHING_HAPPENED, STORY_INTRO, moment_line
from comeback.agents.verifier import (
    allowed_numbers,
    check_length,
    check_names,
    check_numbers,
    check_numerical_claims,
    check_scope,
)
from comeback.agents.workflow import WrittenResult, run_verified
from comeback.fans.catchup import Bucket
from comeback.fans.profiles import FanProfile
from comeback.synth.teams import CLUBS

LANGUAGE_NAMES = {"en": "English", "fr": "French", "es": "Spanish"}
WORD_LIMITS: dict[str, int] = {"line": 30, "key_moments": 80, "full_story": 150}
CHAR_LIMITS: dict[str, int] = {"line": 220, "key_moments": 560, "full_story": 1000}

STORYTELLER_INSTRUCTIONS = """You are the Storyteller of a football companion app. The match, clubs and
players are fictional. A fan was away (or joined late); tell them what they missed.
Write JSON only: {"text": "..."}.
- Write in the requested language, for the requested level:
  casual = simple words, emotion, no jargon or stats acronyms;
  analyst = tactical and precise (xG, control, shape, numerical advantage).
- Point of view: if the fan supports a club, talk to a supporter of that club
  (share their joy or frustration, never mock the opponent). If the fan follows a
  favourite player, put that player at the centre of the story.
- Explain what CHANGED (use the delta block: score then/now, who was in control then/now).
- Respect the word limit. Use ONLY names and numbers that appear in the input.
  Never invent events. Address the fan directly by first name at most once.
- Keep player and club names exactly as written in the input, in every language.
- Check "players_on_pitch_now" before mentioning a numerical advantage: the team
  with fewer players is the one that had a player sent off."""


@dataclass
class CatchupTask:
    """Everything the Storyteller needs for one catch-up."""

    profile: FanProfile
    bucket: Bucket
    cards: list[dict[str, Any]]
    delta: dict[str, Any]
    team_names: dict[str, str]
    roster: dict[str, dict[str, Any]]
    late_join: bool = False


class StorytellerWriter:
    """VerifiedWriter implementation for catch-ups."""

    agent_name = "Storyteller"
    instructions = STORYTELLER_INSTRUCTIONS

    def _favourite_name(self, task: CatchupTask) -> str | None:
        pid = task.profile.favourite_player_id
        return task.roster[pid]["name"] if pid in task.roster else None

    def prompt(self, task: CatchupTask, feedback: list[str]) -> str:
        p = task.profile
        payload: dict[str, Any] = {
            "fan": {
                "first_name": p.name, "language": LANGUAGE_NAMES[p.language], "level": p.level,
                "supports": task.team_names.get(p.club_id) if p.club_id else None,
                "favourite_player": self._favourite_name(task),
            },
            "situation": "joined the match late" if task.late_join else "was away and just came back",
            "word_limit": WORD_LIMITS[task.bucket],
            "delta": task.delta,
            "moments": [
                {"minute": c["minute"], "type": c["type"], "team": task.team_names.get(c["team"]),
                 "headline": c["headline"], "why_it_matters": c["why_it_matters"],
                 "facts": readable_facts(c["facts"], task.team_names)}
                for c in task.cards
            ],
        }
        if feedback:
            payload["fix_these_problems_from_your_previous_draft"] = feedback
        return json.dumps(payload, ensure_ascii=False)

    def parse(self, text: str) -> dict[str, Any]:
        return {"text": str(parse_json_reply(text)["text"]).strip()}

    def verify(self, task: CatchupTask, output: dict[str, Any]) -> list[str]:
        text = output.get("text", "")
        players = set().union(*(moment_player_ids(c) for c in task.cards)) if task.cards else set()
        if task.profile.favourite_player_id:
            players.add(task.profile.favourite_player_id)
        allowed = allowed_numbers([c["facts"] for c in task.cards], [c["minute"] for c in task.cards],
                                  task.delta, WORD_LIMITS[task.bucket])
        issues = check_length(text, CHAR_LIMITS[task.bucket], "text")
        issues += check_numbers(text, allowed)
        issues += check_names(text, players, task.roster, set(task.team_names.values()),
                              {c.name for c in CLUBS.values()})
        on_pitch = task.delta.get("players_on_pitch_now") or {name: 11 for name in task.team_names.values()}
        issues += check_numerical_claims(text, on_pitch)
        issues += check_scope(text)
        return issues

    def fallback(self, task: CatchupTask) -> dict[str, Any]:
        lang = task.profile.language
        intro = (STORY_INTRO if task.late_join else CATCHUP_INTRO)[lang].format(
            minute=task.delta["minute_now"], **{k: task.delta[k] for k in ("away_minutes", "score_then", "score_now")})
        lines = [moment_line(c, lang, task.team_names) for c in task.cards]
        if not lines:
            lines = [NOTHING_HAPPENED[lang].format(score_now=task.delta["score_now"])]
        return {"text": " ".join([intro, *lines])}


async def write_catchup(task: CatchupTask, gateway: LLMGateway) -> dict[str, Any]:
    """Catch-up text plus provenance (via the verified-writing workflow)."""
    result: WrittenResult = await run_verified(StorytellerWriter(), task, gateway)
    return {
        "text": result.output["text"], "source": result.source, "verified": result.verified,
        "attempts": result.attempts, "fallback_reason": result.fallback_reason,
        "bucket": task.bucket, "language": task.profile.language,
        "moment_ids": [c["moment_id"] for c in task.cards], "delta": task.delta,
    }
