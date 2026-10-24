"""Storyteller, "what you missed" lines: one sentence per player and team of the return screen.

The engine has already chosen the players and computed every number (``comeback/fans/missed.py``);
the Storyteller only says why each of them mattered, in the fan's language, through the same
Writer → Verifier → fallback workflow. Lines are written once per (window, language) for the
precomputed windows; any other window keeps the factual template lines (no model call per fan).
"""

import json
from dataclasses import dataclass
from typing import Any

from comeback.agents.llm import PrecomputedOnlyGateway, parse_json_reply
from comeback.agents.storyteller import LANGUAGE_NAMES
from comeback.agents.verifier import (
    allowed_numbers,
    check_length,
    check_names,
    check_no_final_result,
    check_numbers,
    check_numerical_claims,
    check_respect,
    check_scope,
)
from comeback.agents.workflow import Tracer, run_verified
from comeback.synth.teams import CLUBS

MAX_CHARS = 170
NOTES_INSTRUCTIONS = """You are the Storyteller of a football companion app. The match, clubs and
players are fictional. A fan was away (or joined late). The app shows them the players and teams
who changed the game in that window, with numbers computed by the match engine.
Write JSON only: {"players": {"<player name>": "..."}, "teams": {"<team name>": "..."}}.
- One sentence per player and per team, at most 22 words, in the requested language:
  why it mattered for the match (not a list of statistics).
- Say only what the numbers show, without exaggerating: 1 key pass is not "multiple chances",
  a shot is not "sharp shooting", a team with 0 goals in the window did not "turn the game".
- Use ONLY the names and numbers given. Never invent an event. Keep names exactly as written.
- The match is not over: never state a final result.
- Check "players_on_pitch_now" before mentioning a numerical advantage."""


@dataclass
class NotesTask:
    """A "what you missed" payload to write lines for."""

    missed: dict[str, Any]
    roster: dict[str, dict[str, Any]]
    finished: bool = False


def _pick(d: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
    return {k: d[k] for k in keys} if d else None


def _facts(task: NotesTask) -> dict[str, Any]:
    m = task.missed
    keep = ("goals", "assists", "xg", "key_passes", "shots", "progressive_passes", "duels_won", "interceptions",
            "passes_completed", "pass_accuracy")
    return {
        "situation": "joined late: the story so far" if m["late_join"] else "was away and just came back",
        "window": f"{m['from_minute']}' to {m['to_minute']}'",
        "players": [{"name": p["name"], "team": m["teams"][p["team"]]["name"], "position": p["position"],
                     "in_this_window": {k: p["window"][k] for k in keep if p["window"].get(k)}}
                    for p in m["players"]],
        "teams": [{"name": t["name"], "in_this_window": t["window"],
                   "before_the_fan_left": _pick(t["before"], ("shots", "xg", "score")),
                   "now": _pick(t["now"], ("score", "danger", "players_on_pitch"))}
                  for t in m["teams"].values()],
        "players_on_pitch_now": {t["name"]: t["now"]["players_on_pitch"] for t in m["teams"].values()},
    }


class NotesWriter:
    """VerifiedWriter implementation for the return screen's lines."""

    agent_name = "Storyteller"
    instructions = NOTES_INSTRUCTIONS

    def label(self, task: NotesTask) -> str:
        m = task.missed
        return f"what you missed {m['from_minute']}'–{m['to_minute']}' · {m['language'].upper()}"

    def prompt(self, task: NotesTask, feedback: list[str]) -> str:
        payload: dict[str, Any] = {"language": LANGUAGE_NAMES[task.missed["language"]], "facts": _facts(task)}
        if feedback:
            payload["fix_these_problems_from_your_previous_draft"] = feedback
        return json.dumps(payload, ensure_ascii=False)

    def parse(self, text: str) -> dict[str, Any]:
        data = parse_json_reply(text)
        m_names = {**{p["name"]: p["id"] for p in self._task.missed["players"]},
                   **{t["name"]: code for code, t in self._task.missed["teams"].items()}}
        lines = {}
        for group in ("players", "teams"):
            for name, line in (data.get(group) or {}).items():
                if name in m_names:
                    lines[m_names[name]] = str(line).strip()
        return {"lines": lines}

    def verify(self, task: NotesTask, output: dict[str, Any]) -> list[str]:
        m, lines = task.missed, output["lines"]
        wanted = [p["id"] for p in m["players"]] + list(m["teams"])
        issues = [f"Write one line for {self._name(task, key)}." for key in wanted if not lines.get(key)]
        facts = _facts(task)
        allowed = allowed_numbers(facts, [m["from_minute"], m["to_minute"]])
        on_pitch = facts["players_on_pitch_now"]
        team_names = {t["name"] for t in m["teams"].values()}
        for key, line in lines.items():
            issues += check_length(line, MAX_CHARS, f"line for {self._name(task, key)}")
            issues += check_numbers(line, allowed)
            issues += check_names(line, {p["id"] for p in m["players"]}, task.roster, team_names,
                                  {c.name for c in CLUBS.values()})
            issues += check_numerical_claims(line, on_pitch)
            issues += check_scope(line) + check_respect(line) + check_no_final_result(line, task.finished)
        return issues

    @staticmethod
    def _name(task: NotesTask, key: str) -> str:
        return next((p["name"] for p in task.missed["players"] if p["id"] == key), None) \
            or task.missed["teams"][key]["name"]

    def fallback(self, task: NotesTask) -> dict[str, Any]:
        return {"lines": dict(task.missed["lines"])}


class _BoundNotesWriter(NotesWriter):
    """The parser needs the task (to map names back to ids)."""

    def __init__(self, task: NotesTask) -> None:
        self._task = task


async def write_notes(missed: dict[str, Any], roster: dict[str, dict[str, Any]], gateway: Any,
                      trace: Tracer | None = None, finished: bool = False) -> dict[str, Any]:
    """Return ``missed`` with verified LLM lines when this window was precomputed, else its templates."""
    if not missed["players"]:
        return missed
    task = NotesTask(missed, roster, finished)
    result = await run_verified(_BoundNotesWriter(task), task, PrecomputedOnlyGateway(gateway), trace)
    lines = {**missed["lines"], **result.output["lines"]}
    return {**missed, "lines": lines, "source": result.source}
