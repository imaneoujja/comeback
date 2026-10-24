"""Researcher agent: a commentator's talking points for a key moment, from the league's records.

For each key moment the league module picks one or two context facts with their source (the
scorer's season, the table if the score holds, form, head-to-head, injuries, suspensions:
``comeback/league.py``). The Researcher turns them into one sentence each, in the studio's
language, through the same Writer → Verifier → fallback workflow: every number and name must
come from those facts. Written once per (moment, language) for the precomputed demo; any other
moment keeps the factual template sentence (no model call per viewer).
"""

import json
import re
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
    check_respect,
)
from comeback.agents.workflow import Tracer, run_verified
from comeback.league import League, ordinal

MAX_CHARS = 200
RESEARCHER_INSTRUCTIONS = """You are the Researcher of a football broadcast studio. The league, clubs and players
are fictional. For a key moment of the live match you receive context facts from the league's records.
Write JSON only: {"points": ["...", "..."]} — exactly one sentence per fact, in the requested language,
at most 25 words each: a talking point a commentator can say on air right now.
- Use ONLY the names and numbers in the facts; never invent a statistic, a record or an event.
- Keep player and club names exactly as written. Ordinals are fine ("13th goal of the season").
- The match is not over unless the moment is full-time: never state a final result."""

FORM_LETTERS = {"en": {"W": "W", "D": "D", "L": "L"}, "fr": {"W": "V", "D": "N", "L": "D"},
                "es": {"W": "V", "D": "E", "L": "D"}}
REASONS = {
    "hamstring strain": {"fr": "ischio-jambiers", "es": "isquiotibiales"},
    "ankle sprain": {"fr": "entorse à la cheville", "es": "esguince de tobillo"},
    "knee ligament": {"fr": "ligaments du genou", "es": "ligamento de la rodilla"},
    "thigh strain": {"fr": "blessure à la cuisse", "es": "lesión en el muslo"},
    "concussion protocol": {"fr": "protocole commotion", "es": "protocolo de conmoción"},
}
TEMPLATES: dict[str, dict[str, str]] = {
    "scorer_season": {
        "en": "{nth} goal of the season for {name}, {recent} in the last {last_apps} matches.",
        "fr": "{nth} but de la saison pour {name}, {recent} sur les {last_apps} derniers matchs.",
        "es": "{nth} gol de la temporada para {name}, {recent} en los últimos {last_apps} partidos.",
    },
    "player_xg": {
        "en": "{name} this season: {goals} goals from {xg} xG in {apps} matches.",
        "fr": "{name} cette saison : {goals} buts pour {xg} xG en {apps} matchs.",
        "es": "{name} esta temporada: {goals} goles con {xg} xG en {apps} partidos.",
    },
    "suspension": {
        "en": "{name} is now suspended for matchday {matchday}, against {opponent}.",
        "fr": "{name} sera suspendu pour la {matchday}e journée, contre {opponent}.",
        "es": "{name} queda suspendido para la jornada {matchday}, ante {opponent}.",
    },
    "absence": {
        "en": "{team} are without {name} ({reason}).",
        "fr": "{team} est privé de {name} ({reason}).",
        "es": "{team} no cuenta con {name} ({reason}).",
    },
    "form": {
        "en": "{team}: {form} in their last five, {pos} in the table before kick-off.",
        "fr": "{team} : {form} sur les cinq derniers matchs, {pos} au classement avant le coup d'envoi.",
        "es": "{team}: {form} en los últimos cinco, {pos} en la tabla antes del inicio.",
    },
    "table_up": {
        "en": "If it ends {score}, {team} move up from {pos_before} to {pos_after}.",
        "fr": "Si le score reste {score}, {team} passe de la {pos_before} à la {pos_after} place.",
        "es": "Si termina {score}, {team} sube del {pos_before} al {pos_after} puesto.",
    },
    "table_down": {
        "en": "If it ends {score}, {team} drop from {pos_before} to {pos_after}.",
        "fr": "Si le score reste {score}, {team} recule de la {pos_before} à la {pos_after} place.",
        "es": "Si termina {score}, {team} baja del {pos_before} al {pos_after} puesto.",
    },
    "table_same": {
        "en": "If it ends {score}, {team} stay {pos_after} in the table.",
        "fr": "Si le score reste {score}, {team} reste {pos_after} au classement.",
        "es": "Si termina {score}, {team} sigue {pos_after} en la tabla.",
    },
    "table_final": {
        "en": "With this {score}, {team} are {pos_after} in the table ({pos_before} before kick-off).",
        "fr": "Avec ce {score}, {team} est {pos_after} au classement ({pos_before} avant le coup d'envoi).",
        "es": "Con este {score}, {team} queda {pos_after} en la tabla ({pos_before} antes del inicio).",
    },
    "h2h": {
        "en": "Last meeting: {home} {score} {away} ({season}, matchday {matchday}).",
        "fr": "Dernière confrontation : {home} {score} {away} ({season}, {matchday}e journée).",
        "es": "Último enfrentamiento: {home} {score} {away} ({season}, jornada {matchday}).",
    },
}


# Claims a phrasing can get wrong although every number and name is right (each one seen in a real draft).
_SCORE = r"\d+\s*[-–]\s*\d+"
_LEADING = re.compile(rf"{_SCORE}\s+(?:lead|d['’]avance)|(?:lead(?:ing)?|ahead|avance de|mènen?t?|ventaja(?: de)?"
                      rf"|lideran?|ganando(?: por)?)\s+{_SCORE}", re.IGNORECASE)
_TRAILING = re.compile(rf"(?:trail(?:ing|s)?|behind|perdiendo(?: por)?|mené[es]?(?: par)?)\s+{_SCORE}", re.IGNORECASE)
_WON = re.compile(rf"{_SCORE}\s+(?:win|victory|victoire|victoria)|\b(?:win over|vencer|tras vencer|remport\w*)\b",
                  re.IGNORECASE)
_ABOVE_XG = re.compile(r"superando|supera\w*|clinical|clinique|outperform\w*|above (?:his |the )?(?:expected|xg)"
                       r"|au-dessus|dépass\w*|efficac\w*|eficac\w*|letal", re.IGNORECASE)
_BELOW_XG = re.compile(r"below (?:his |the )?(?:expected|xg)|underperform\w*|en dessous|por debajo|wasteful|maladroit",
                       re.IGNORECASE)
_LAST_SEASON = re.compile(r"last season|saison (?:dernière|passée)|temporada pasada|pasada temporada", re.IGNORECASE)
_THIS_SEASON = re.compile(r"this season|cette saison|esta temporada", re.IGNORECASE)
_OBJECT = re.compile(r"\b(?:at|against|over|v|vs|en|à|a|contre|face aux?|aux|ante|frente a|sobre|de|del)\s+$",
                     re.IGNORECASE)
_FIRST_MEETING = re.compile(r"first (?:meeting|encounter|time)|premi[eè]re (?:confrontation|rencontre|fois)"
                            r"|primer (?:enfrentamiento|encuentro)", re.IGNORECASE)
_ALL_OF_THEM = re.compile(r"\b(?:all|both|tous|toutes|ambos|todos)\b", re.IGNORECASE)


def check_claims(point: str, fact: dict[str, Any], score: tuple[int, int], clubs: tuple[str, str],
                 this_season: str, finished: bool) -> list[str]:
    """Who leads, over/under xG, which season, "all of them": the facts say it, the sentence must agree."""
    issues = []
    named = sorted((point.find(name), side) for side, name in enumerate(clubs)
                   if name and name in point and not _OBJECT.search(point[:point.find(name)]))
    if named and score[0] != score[1]:
        subject = named[0][1]                       # the first club named outside "at X", "contre X"… is the subject
        leads = (score[subject] > score[1 - subject])
        if (_LEADING.search(point) and not leads) or (_TRAILING.search(point) and leads):
            issues.append(f"Wrong side: the score is {clubs[0]} {score[0]}-{score[1]} {clubs[1]}.")
    if not finished and _WON.search(point):
        issues.append("The match is not over: do not call the score a win.")
    if fact["kind"] == "player_xg":
        if fact["goals"] < fact["xg"] and _ABOVE_XG.search(point):
            issues.append(f"{fact['name']} has scored fewer goals ({fact['goals']}) than the xG ({fact['xg']}).")
        if fact["goals"] > fact["xg"] and _BELOW_XG.search(point):
            issues.append(f"{fact['name']} has scored more goals ({fact['goals']}) than the xG ({fact['xg']}).")
    if fact["kind"] == "h2h":
        wrong = _LAST_SEASON if fact["season"] == this_season else _THIS_SEASON
        if wrong.search(point):
            issues.append(f"That meeting was in {fact['season']}.")
        if _FIRST_MEETING.search(point):
            issues.append("Today is not their first meeting: the last one is in the facts.")
    if fact["kind"] == "scorer_season" and fact["recent"] < fact["nth"] and _ALL_OF_THEM.search(point):
        issues.append(f"Only {fact['recent']} of the {fact['nth']} goals came in the last {fact['last_apps']} matches.")
    return issues


def template_point(fact: dict[str, Any], lang: str) -> str:
    """The factual sentence for one fact, in ``lang``."""
    v = {**fact}
    kind = fact["kind"]
    if kind == "scorer_season":
        v["nth"] = ordinal(fact["nth"], lang)
        v["nth"] = v["nth"][:1].upper() + v["nth"][1:]
    elif kind == "form":
        v["form"] = "".join(FORM_LETTERS[lang][c] for c in fact["form"])
        v["pos"] = ordinal(fact["pos"], lang)
    elif kind == "absence":
        v["reason"] = REASONS.get(fact["reason"], {}).get(lang, fact["reason"])
    elif kind == "table_if" and fact.get("final"):
        kind = "table_final"
        v["pos_before"], v["pos_after"] = ordinal(fact["pos_before"], lang), ordinal(fact["pos_after"], lang)
    elif kind == "table_if":
        kind = "table_up" if fact["pos_after"] < fact["pos_before"] else "table_down" \
            if fact["pos_after"] > fact["pos_before"] else "table_same"
        v["pos_before"], v["pos_after"] = ordinal(fact["pos_before"], lang), ordinal(fact["pos_after"], lang)
    return TEMPLATES[kind][lang].format(**v)


@dataclass
class ResearchTask:
    """One moment's talking points to write."""

    card: dict[str, Any]
    facts: list[dict[str, Any]]
    language: str
    team_names: dict[str, str]
    roster: dict[str, dict[str, Any]]
    league_clubs: set[str]
    clubs: tuple[str, str] = ("", "")       # today's home and away names
    season: str = ""

    @property
    def score(self) -> tuple[int, int]:
        facts = self.card.get("facts", {})
        home, away = (facts.get("score_after") or facts.get("score") or "0-0").split("-")
        return int(home), int(away)


def _public(fact: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fact.items() if k != "source"}


class ResearchWriter:
    """VerifiedWriter implementation for talking points."""

    agent_name = "Researcher"
    instructions = RESEARCHER_INSTRUCTIONS

    def label(self, task: ResearchTask) -> str:
        return f"{task.card['minute']}' {task.card['type'].replace('_', ' ')}"

    def prompt(self, task: ResearchTask, feedback: list[str]) -> str:
        c = task.card
        payload: dict[str, Any] = {
            "language": LANGUAGE_NAMES[task.language],
            "moment": {"minute": c["minute"], "type": c["type"].replace("_", " "),
                       "team": task.team_names.get(c.get("team"), None), "headline": c.get("headline")},
            "facts": [_public(f) for f in task.facts],
        }
        if feedback:
            payload["fix_these_problems_from_your_previous_draft"] = feedback
        return json.dumps(payload, ensure_ascii=False)

    def parse(self, text: str) -> dict[str, Any]:
        points = parse_json_reply(text).get("points") or []
        return {"points": [str(p).strip() for p in points if str(p).strip()]}

    def verify(self, task: ResearchTask, output: dict[str, Any]) -> list[str]:
        points = output.get("points", [])
        issues = [] if len(points) == len(task.facts) else [f"Write exactly {len(task.facts)} talking points."]
        window = [5] if any(f["kind"] == "form" for f in task.facts) else []     # "in the last 5"
        finished = task.card["type"] == "full_time"
        allowed = allowed_numbers([_public(f) for f in task.facts], window)    # not the minute: drafts misdate goals
        named = {f[k] for f in task.facts for k in ("name",) if k in f}
        players = {pid for pid, info in task.roster.items() if info["name"] in named}
        for point, fact in zip(points, task.facts, strict=False):
            issues += check_length(point, MAX_CHARS, "talking point")
            issues += check_numbers(point, allowed)
            issues += check_names(point, players, task.roster, task.league_clubs, task.league_clubs)
            issues += check_respect(point)
            if fact["kind"] == "table_if":      # the only point about today's score; form and h2h are past results
                issues += check_no_final_result(point, finished)
            issues += check_claims(point, fact, task.score, task.clubs, task.season, finished)
        return issues

    def fallback(self, task: ResearchTask) -> dict[str, Any]:
        return {"points": [template_point(f, task.language) for f in task.facts]}


async def talking_points(card: dict[str, Any], league: League, home: str, away: str, language: str,
                         team_names: dict[str, str], roster: dict[str, dict[str, Any]], gateway: Any,
                         trace: Tracer | None = None) -> dict[str, Any] | None:
    """Talking points for one moment card, or None when the league has nothing to add."""
    facts = league.talking_facts(card, home, away)
    if not facts:
        return None
    task = ResearchTask(card, facts, language, team_names, roster, set(league.clubs.values()),
                        (league.clubs[home], league.clubs[away]), league.data["season"])
    result = await run_verified(ResearchWriter(), task, PrecomputedOnlyGateway(gateway), trace)
    points = result.output["points"]
    return {"moment_id": card["moment_id"], "minute": card["minute"], "type": card["type"], "team": card.get("team"),
            "language": language, "source": result.source,
            "points": [{"text": text, "source": f["source"]} for text, f in zip(points, facts, strict=False)]}
