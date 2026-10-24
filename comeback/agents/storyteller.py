"""Storyteller agent: a personalised "previously on…" catch-up for a returning fan.

Input: the verified Moment Cards of the away window, a delta block (what changed)
and the fan profile. Output: text in the fan's language, level and point of view,
sized to the absence. Goes through the same Writer → Verifier → fallback workflow.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from comeback.agents.analyst import moment_player_ids, readable_facts
from comeback.agents.llm import LLMGateway, parse_json_reply
from comeback.agents.templates import (
    CATCHUP_INTRO,
    FINAL_GAP,
    FINAL_INTRO,
    NOTHING_HAPPENED,
    STORY_INTRO,
    moment_line,
)
from comeback.agents.verifier import (
    allowed_numbers,
    check_comparisons,
    check_length,
    check_names,
    check_no_final_result,
    check_numbers,
    check_numerical_claims,
    check_omissions,
    check_respect,
    check_scope,
)
from comeback.agents.workflow import Tracer, WrittenResult, run_verified
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
- If they were away, they did NOT see what happened: start with what happened while
  they were away (or, for a late join, the story so far), then what it changes now.
- Explain what CHANGED (use the delta block: score then/now, who was in control then/now).
- Respect the word limit. Use ONLY names and numbers that appear in the input.
  Never invent events. Address the fan directly as "you"; there is no name, never invent one.
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
    final: bool = False          # full-time recap ("Gazette"): also needs a headline
    scores: list[tuple[int, int]] = field(default_factory=list)   # after each goal of the match (omission check)


PROMPT_DELTA_KEYS = ("score_then", "score_now", "in_control_then", "in_control_now",
                     "players_on_pitch_now", "key_changes")


def labelled_score(score: str | None, team_names: dict[str, str]) -> str | None:
    """'1-2' → 'Emberfield 1-2 Saltmarsh Comets' (home first), so no model misreads who leads."""
    if not score:
        return None
    home, away = team_names.values()
    return f"{home} {score} {away}"


def prompt_delta(delta: dict[str, Any], late_join: bool, team_names: dict[str, str]) -> dict[str, Any]:
    """The delta block without exact minutes: two absences covering the same moments share one story."""
    out = {k: delta[k] for k in PROMPT_DELTA_KEYS if k in delta}
    for key in ("score_then", "score_now"):
        out[key] = labelled_score(out.get(key), team_names)
    if late_join:
        out["minute_now"] = delta["minute_now"]
    return out


def goal_scores(cards: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """The score after each goal among the cards, in match order (home, away)."""
    out = []
    for c in sorted(cards, key=lambda c: c["t"]):
        score = c["facts"].get("score_after") if c["type"] == "goal" else None
        if score:
            home, away = score.split("-")
            out.append((int(home), int(away)))
    return out


class StorytellerWriter:
    """VerifiedWriter implementation for catch-ups."""

    agent_name = "Storyteller"
    instructions = STORYTELLER_INSTRUCTIONS

    def label(self, task: CatchupTask) -> str:
        what = "full-time recap" if task.final else "story so far" if task.late_join else task.bucket.replace("_", " ")
        return f"{task.profile.display} · {what}"

    def _favourite_name(self, task: CatchupTask) -> str | None:
        pid = task.profile.favourite_player_id
        return task.roster[pid]["name"] if pid in task.roster else None

    @staticmethod
    def _situation(task: CatchupTask) -> str:
        if task.final:
            return "the match is over: write their full-time recap, with a newspaper headline"
        return "joined the match late" if task.late_join else "was away and just came back"

    def prompt(self, task: CatchupTask, feedback: list[str]) -> str:
        p = task.profile
        payload: dict[str, Any] = {
            "fan": {
                "language": LANGUAGE_NAMES[p.language], "level": p.level,
                "supports": task.team_names.get(p.club_id) if p.club_id else None,
                "favourite_player": self._favourite_name(task),
            },
            "situation": self._situation(task),
            "word_limit": WORD_LIMITS[task.bucket],
            "delta": prompt_delta(task.delta, task.late_join, task.team_names),
            "moments": [
                {"minute": c["minute"], "type": c["type"], "team": task.team_names.get(c["team"]),
                 "score_after_this_moment": labelled_score(
                     c["facts"].get("score_after") or c["facts"].get("score"), task.team_names),
                 "headline": c["headline"], "why_it_matters": c["why_it_matters"],
                 "facts": readable_facts(c["facts"], task.team_names)}
                for c in task.cards
            ],
        }
        if task.final:
            payload["output"] = 'JSON {"headline": "...max 10 words, from the fan\'s side...", "text": "..."}'
        if feedback:
            payload["fix_these_problems_from_your_previous_draft"] = feedback
        return json.dumps(payload, ensure_ascii=False)

    def parse(self, text: str) -> dict[str, Any]:
        data = parse_json_reply(text)
        out = {"text": str(data["text"]).strip()}
        if data.get("headline"):
            out["headline"] = str(data["headline"]).strip()
        return out

    def verify(self, task: CatchupTask, output: dict[str, Any]) -> list[str]:
        text = f"{output.get('headline', '')}\n{output.get('text', '')}".strip()
        players = set().union(*(moment_player_ids(c) for c in task.cards)) if task.cards else set()
        if task.profile.favourite_player_id:
            players.add(task.profile.favourite_player_id)
        allowed = allowed_numbers([c["facts"] for c in task.cards], [c["minute"] for c in task.cards],
                                  task.delta, WORD_LIMITS[task.bucket])
        issues = check_length(output.get("text", ""), CHAR_LIMITS[task.bucket], "text")
        if task.final:
            issues += check_length(output.get("headline", ""), 90, "headline")
        issues += check_numbers(text, allowed)
        issues += check_names(text, players, task.roster, set(task.team_names.values()),
                              {c.name for c in CLUBS.values()})
        on_pitch = task.delta.get("players_on_pitch_now") or {name: 11 for name in task.team_names.values()}
        issues += check_numerical_claims(text, on_pitch, task.team_names.get(task.profile.pov_team() or ""))
        issues += check_scope(text)
        issues += check_no_final_result(text, task.final or any(c["type"] == "full_time" for c in task.cards))
        issues += check_respect(text)
        for card in task.cards:
            issues += check_comparisons(text, card["facts"], task.team_names)
        if task.final:
            issues += check_omissions(text, task.scores or goal_scores(task.cards), task.team_names)
        return issues

    def fallback(self, task: CatchupTask) -> dict[str, Any]:
        lang = task.profile.language
        intro = (FINAL_INTRO if task.final else STORY_INTRO if task.late_join else CATCHUP_INTRO)[lang].format(
            minute=task.delta["minute_now"], **{k: task.delta[k] for k in ("away_minutes", "score_then", "score_now")})
        lines = [moment_line(c, lang, task.team_names) for c in task.cards]
        if not lines:
            lines = [NOTHING_HAPPENED[lang].format(score_now=task.delta["score_now"])]
        home, away = task.team_names.values()
        if task.final and check_omissions(" ".join(lines), task.scores, task.team_names):
            a, b = max(task.scores, key=lambda s: abs(s[0] - s[1]))
            if abs(a - b) >= 2:
                lines.append(FINAL_GAP[lang].format(home=home, away=away, a=a, b=b))
        out = {"text": " ".join([intro, *lines])}
        if task.final:
            out["headline"] = f"{home} {task.delta['score_now']} {away}"
        return out


async def write_catchup(task: CatchupTask, gateway: LLMGateway, trace: Tracer | None = None) -> dict[str, Any]:
    """Catch-up text plus provenance (via the verified-writing workflow)."""
    result: WrittenResult = await run_verified(StorytellerWriter(), task, gateway, trace)
    return {
        "text": result.output["text"], "headline": result.output.get("headline"),
        "source": result.source, "verified": result.verified, "final": task.final,
        "attempts": result.attempts, "fallback_reason": result.fallback_reason,
        "bucket": task.bucket, "language": task.profile.language,
        "moment_ids": [c["moment_id"] for c in task.cards], "delta": task.delta,
    }
