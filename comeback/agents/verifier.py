"""Verifier agent (rule-based): fact-checks every generated text before a fan sees it.

Checks, with precise feedback for the writer's retry:
* every number in the text exists in the facts it was given (with rounding / % tolerance),
* no player who is not part of the facts is named, no club outside the match is named,
* no claims beyond this match (season, league, career), length limits.
"""

import re
from typing import Any

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PLAYER_ID = re.compile(r"^[A-Z]{3}-\d+$")  # e.g. "EMB-9": an id, not a statistic
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
    r"man down|men down|down to (?:10|ten)|(?:10|ten) men|(?:10|ten)-man|a player down|down a player"
    r"|numerical disadvantage"
    r"|player disadvantage|infériorité numérique|à dix|réduits? à (?:10|dix)|inferioridad numérica|con diez"
    r"|con 10",
    re.IGNORECASE,
)
_EXTRA_MAN = re.compile(
    r"numerical advantage|extra man|man advantage|player advantage|numerical superiority|full[- ]strength"
    r"|supériorité numérique|homme de plus|superioridad numérica|jugador más",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?。！？\n]+")
_OPPOSING = re.compile(
    r"\b(?:against|versus|vs\.?|facing|face|contre|face à|contra|ante)\s+(?:the |a |an |les? |la |l['’]|el |los )?$",
    re.IGNORECASE,
)
_EQUAL_NUMBERS_CLAIM = re.compile(   # like _EXTRA_MAN, minus "full strength" (true when both teams have 11)
    _SHORT_HANDED.pattern + r"|numerical advantage|extra man|man advantage|player advantage|numerical superiority"
    r"|supériorité numérique|superioridad numérica",
    re.IGNORECASE,
)
_OVERCOMING = re.compile(
    r"\b(?:overcom\w*|overturn\w*|surmont\w*|superando|superar)\s+(?:a |an |the |une |la |el )?$", re.IGNORECASE
)
_FOR_TEAM = re.compile(r"^\s*(?:for|of|to|pour|des|de|du|d['’]|para|a favor de|del)\s*(?:the |les? |la |el |los )?",
                       re.IGNORECASE)
_GENERIC_WORDS = {"FC", "United", "City", "Athletic", "St.", "Point"}
# In a fan's own catch-up, "you" / "we" / "your team" / "l'équipe" / "quedamos" is the fan's side.
_FAN_SIDE = re.compile(
    r"\b(?:you|we|us|your (?:team|side|club)|nous|nos|quedamos|estamos|jugamos)\b"
    r"|\b(?:ton|votre|notre) équipe\b|\bl['’]équipe\b(?! adverse)"
    r"|\b(?:tu|vuestro|nuestro) equipo\b|\bel equipo\b(?! rival)",
    re.IGNORECASE,
)


def _team_tokens(name: str) -> set[str]:
    return {w for w in name.split() if w not in _GENERIC_WORDS} | {name}


def check_numerical_claims(text: str, players_on_pitch: dict[str, int], fan_team: str | None = None) -> list[str]:
    """A numerical disadvantage claim must be about the short-handed team, an advantage claim about the other.

    A claim is attached to the team named just before it in the sentence (usually the
    subject: "Comets must defend with 10 men"), or to the team just after it when it
    follows "against / versus / face à…" ("against ten-man Comets") or is followed by
    "for / of / pour…" ("a numerical advantage for Emberfield"). No team named → ambiguous.
    In a fan's own text, ``fan_team`` is the fan's side: "leaving you with 10 men" names it.
    """
    if len(set(players_on_pitch.values())) < 2:
        if _EQUAL_NUMBERS_CLAIM.search(text):
            return ["Both teams have the same number of players: do not mention a numerical (dis)advantage."]
        return []
    short = min(players_on_pitch, key=players_on_pitch.get)
    full = max(players_on_pitch, key=players_on_pitch.get)
    issues = []
    claims = [(_SHORT_HANDED, short, "disadvantage"), (_EXTRA_MAN, full, "advantage")]
    for sentence in _SENTENCE.findall(text):
        for pattern, expected, kind in claims:
            issue = _misattributed(sentence, pattern, expected, kind, short, full, players_on_pitch, fan_team)
            if issue:
                issues.append(issue)
                break
    return issues


def _misattributed(sentence: str, pattern: re.Pattern, expected: str, kind: str, short: str, full: str,
                   players_on_pitch: dict[str, int], fan_team: str | None = None) -> str | None:
    """Feedback if a numerical (dis)advantage claim in ``sentence`` is attached to the wrong team."""
    for claim in pattern.finditer(sentence):
        mentions = [(m.start(), m.end(), team) for team in (short, full) for token in _team_tokens(team)
                    for m in re.finditer(re.escape(token), sentence)]
        if fan_team in (short, full):
            mentions += [(m.start(), m.end(), fan_team) for m in _FAN_SIDE.finditer(sentence)]
        before = [(claim.start() - end, team) for start, end, team in mentions if end <= claim.start()]
        after = [(start - claim.end(), team) for start, end, team in mentions if start >= claim.end()]
        owner = expected
        opposing = _OPPOSING.search(sentence[:claim.start()])
        if after and (opposing or _FOR_TEAM.match(sentence[claim.end():])):
            attached = min(after)[1]          # explicit owner: "against ten-man X", "an advantage for X"
        elif opposing and before:             # "X … against ten men": the ten men are X's opponents
            nearest = min(before)[1]
            attached = full if nearest == short else short
        elif before or after:
            attached = min(before or after)[1]
            if _OVERCOMING.search(sentence[:claim.start()]):   # "X won, overcoming a numerical advantage":
                owner = full if expected == short else short   # the advantage was the other side's
        else:
            attached = None
        if attached != owner:
            return (f"'{sentence.strip()}': {short} is short-handed ({players_on_pitch[short]} players) and "
                    f"{full} has {players_on_pitch[full]}, so the numerical {kind} belongs to {expected}. "
                    f"Attach it to {expected} explicitly.")
    return None


_FINAL_RESULT = re.compile(   # "drew level" and "el empate" (the equaliser) happen mid-match: not a result
    r"\b(?:won|wins|win the match|victory|draw(?! level)|drew(?! level)|defeat|lost the match|victoire|match nul"
    r"|gagn[ée]|d[ée]faite|victoria|un empate|(?:termin|acab|finaliz)\w*\s+(?:en\s+)?(?:un\s+)?empate"
    r"|ganaron|derrota)\b",
    re.IGNORECASE,
)


def check_no_final_result(text: str, finished: bool) -> list[str]:
    """Before full-time, a text must not talk as if the match were already won, drawn or lost."""
    if finished:
        return []
    found = sorted({m.group(0).lower() for m in _FINAL_RESULT.finditer(text)})
    if found:
        return [f"The match is not over: do not describe a final result ({', '.join(found)}). "
                "Say who leads or that the score is level right now."]
    return []


# Responsible AI: fans are told about people. No insults, no mockery of a player, and no betting.
_DISRESPECT = re.compile(
    r"\b(?:useless|idiot\w*|stupid\w*|pathetic|disgrace\w*|clown\w*|flop|rubbish|garbage|incompetent|laughable"
    r"|humiliat\w*|imb[ée]cile\w*|minable\w*|lamentable\w*|honte\w*|ridicule\w*|nullard\w*"
    r"|in[úu]til\w*|pat[ée]tic\w*|verg[üu]enza|payaso\w*|rid[íi]cul\w*)\b",
    re.IGNORECASE,
)
_BETTING = re.compile(
    r"\b(?:odds|bet|bets|betting|wager\w*|bookmaker\w*|bookie\w*|paris sportifs?|cotes?|apuestas?|cuotas?)\b",
    re.IGNORECASE,
)


def check_respect(text: str) -> list[str]:
    """No insulting or mocking words about players or clubs, and no betting talk (odds, bets)."""
    issues = []
    insults = sorted({m.group(0).lower() for m in _DISRESPECT.finditer(text)})
    if insults:
        issues.append(f"Be respectful of players and clubs: remove {', '.join(insults)}.")
    betting = sorted({m.group(0).lower() for m in _BETTING.finditer(text)})
    if betting:
        issues.append(f"No betting talk: remove {', '.join(betting)}.")
    return issues


# Comparative claims ("despite fewer chances", "more possession") must match the per-team stats.
_COMPARISONS = [  # (pattern, stat, direction: -1 = the team has less, +1 = more)
    (r"fewer (?:chances|shots|opportunities)|less (?:threat|xg)"
     r"|moins d['’]occasions|moins de tirs|menos ocasiones|menos tiros", "shots", -1),
    (r"more (?:chances|shots|opportunities)|outshot"
     r"|plus d['’]occasions|plus de tirs|más ocasiones|más tiros", "shots", +1),
    (r"less (?:of the )?(?:ball|possession)|moins de possession|menos posesi[óo]n", "possession", -1),
    (r"more (?:of the )?(?:ball|possession)|dominated possession|plus de possession|más posesi[óo]n", "possession", +1),
]


def check_comparisons(text: str, facts: dict, team_names: dict[str, str]) -> list[str]:
    """A claim that a team had fewer/more chances or less/more possession must agree with the facts."""
    stats = {team_names[code]: facts[code] for code in team_names
             if isinstance(facts.get(code), dict) and "shots" in facts[code] and "possession" in facts[code]}
    if len(stats) != 2:
        return []
    issues = []
    for sentence in _SENTENCE.findall(text):
        for pattern, stat, direction in _COMPARISONS:
            for claim in re.finditer(pattern, sentence, re.IGNORECASE):
                before = [(claim.start() - m.end(), name) for name in stats for token in _team_tokens(name)
                          for m in re.finditer(re.escape(token), sentence[:claim.start()])]
                if not before:
                    continue
                team = min(before)[1]
                other = next(name for name in stats if name != team)
                if (stats[team][stat] - stats[other][stat]) * direction <= 0:
                    issues.append(f"'{sentence.strip()}': {team} had {stats[team][stat]} {stat} and {other} "
                                  f"{stats[other][stat]}, so '{claim.group(0)}' is wrong. Use the facts.")
    return issues
