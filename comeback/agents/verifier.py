"""Verifier agent (rule-based): fact-checks every generated text before a fan sees it.

Checks, with precise feedback for the writer's retry:
* every number in the text exists in the facts it was given (with rounding / % tolerance),
* no player who is not part of the facts is named, no club outside the match is named,
* no claims beyond this match (season, league, career), length limits.
"""

import re
from typing import Any

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PLAYER_ID = re.compile(r"^[A-Z]{3}-\d+$")  # e.g. "RVR-9": an id, not a statistic
_OUT_OF_SCOPE = re.compile(
    r"\b(?:season|league|career|all-time|history|saison|championnat|carrière|histoire|temporada|liga"
    r"|carrera|historia)\b",
    re.IGNORECASE,
)
ALWAYS_ALLOWED = {1.0, 2.0, 45.0, 90.0}


def numbers_in(value: Any) -> set[float]:
    """All numbers found in a (possibly nested) value, including inside strings like "0-2"."""
    found: set[float] = set()
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float)):
        found.add(float(value))
    elif isinstance(value, str) and not _PLAYER_ID.match(value):
        found |= {float(n.replace(",", ".")) for n in _NUMBER.findall(value)}
    elif isinstance(value, dict):
        for v in value.values():
            found |= numbers_in(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            found |= numbers_in(v)
    return found


def allowed_numbers(*sources: Any) -> set[float]:
    """Numbers a text may use: those in the sources plus readable variants (rounded, %, 90+x)."""
    base = set(ALWAYS_ALLOWED)
    for source in sources:
        base |= numbers_in(source)
    allowed = set(base)
    for n in base:
        allowed |= {float(round(n)), round(n, 1), round(n, 2)}
        if 0 < n < 1:
            allowed |= {float(round(n * 100)), round(n * 100, 1)}
        if 90 < n < 100:
            allowed.add(n - 90)
        if 45 < n < 55:
            allowed.add(n - 45)
    return allowed


def check_numbers(text: str, allowed: set[float]) -> list[str]:
    """Feedback for numbers that do not come from the facts."""
    bad = []
    for raw in _NUMBER.findall(text):
        n = float(raw.replace(",", "."))
        if not any(abs(n - a) < 1e-6 for a in allowed):
            bad.append(raw)
    if not bad:
        return []
    return [f"These numbers are not in the facts: {', '.join(sorted(set(bad)))}. "
            "Use only numbers that appear in the facts (or remove them)."]


def check_names(text: str, allowed_player_ids: set[str], roster: dict[str, dict[str, Any]],
                match_clubs: set[str], all_clubs: set[str]) -> list[str]:
    """Feedback for players not involved in the facts, or clubs outside this match."""
    issues = []
    allowed_surnames = {roster[p]["name"].split()[-1] for p in allowed_player_ids if p in roster}
    for pid, info in roster.items():
        if pid in allowed_player_ids:
            continue
        full, surname = info["name"], info["name"].split()[-1]
        named = full in text or (surname not in allowed_surnames and re.search(rf"\b{re.escape(surname)}\b", text))
        if named:
            issues.append(f"'{full}' is not part of these facts: do not mention this player.")
    for club in all_clubs - match_clubs:
        if club in text:
            issues.append(f"'{club}' does not play in this match: do not mention it.")
    return issues


def check_scope(text: str) -> list[str]:
    """The facts only cover this match: no season, league, career or all-time claims."""
    found = sorted({m.group(0) for m in _OUT_OF_SCOPE.finditer(text)})
    if found:
        return [f"Only talk about this match: remove claims about {', '.join(found)} (not in the facts)."]
    return []


def check_length(text: str, max_chars: int, label: str) -> list[str]:
    """Feedback when a text is empty or too long."""
    if not text.strip():
        return [f"The {label} is empty."]
    if len(text) > max_chars:
        return [f"The {label} is {len(text)} characters long; the limit is {max_chars}. Make it shorter."]
    return []



_SHORT_HANDED = re.compile(
    r"man down|men down|down to (?:10|ten)|(?:10|ten) men|a player down|down a player|numerical disadvantage"
    r"|player disadvantage|infériorité numérique|à dix|réduits? à (?:10|dix)|inferioridad numérica|con diez"
    r"|con 10",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?。！？]+")
_GENERIC_WORDS = {"FC", "United", "City", "Athletic", "St.", "Point"}


def _team_tokens(name: str) -> set[str]:
    return {w for w in name.split() if w not in _GENERIC_WORDS} | {name}


def check_numerical_claims(text: str, players_on_pitch: dict[str, int]) -> list[str]:
    """A "playing with ten men" claim must name the short-handed team, and only that team."""
    if len(set(players_on_pitch.values())) < 2:
        if _SHORT_HANDED.search(text):
            return ["Both teams have the same number of players: do not mention a numerical disadvantage."]
        return []
    short = min(players_on_pitch, key=players_on_pitch.get)
    full = max(players_on_pitch, key=players_on_pitch.get)
    issues = []
    for sentence in _SENTENCE.findall(text):
        if not _SHORT_HANDED.search(sentence):
            continue
        names_short = any(t in sentence for t in _team_tokens(short))
        if not names_short:
            issues.append(f"'{sentence.strip()}': only {short} is short-handed ({players_on_pitch[short]} "
                          f"players); {full} has {players_on_pitch[full]}. Name {short} explicitly when "
                          "mentioning the numerical disadvantage.")
    return issues
