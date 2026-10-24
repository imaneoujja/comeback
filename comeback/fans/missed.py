"""What you missed: the players and teams who changed the game while the fan was away.

Every number comes from the match engine: the events of the absence window are replayed
into a fresh :class:`MatchState`, so the window has its own passes, shots, xG, key passes,
duels and top speeds. Players are ranked by a transparent influence score (``INFLUENCE``):
the screen shows the terms that put each player in the top three. Teams are compared with
the match as the fan left it. The "why it matters" lines default to factual templates in
the fan's language; for precomputed windows a verified LLM line replaces them
(``comeback/agents/notes.py``).
"""

from typing import Any

from comeback.engine.state import MatchState, PlayerStats

# Influence = Σ weight × stat over the window. Goals and chances count fully; volume (forward
# passes, duels, interceptions, completed passes) is capped so a long window ranks the players
# who decided it, not the ones who touched the ball most. (stat, weight, cap or None)
INFLUENCE: tuple[tuple[str, float, float | None], ...] = (
    ("goals", 15.0, None), ("assists", 8.0, None), ("xg", 10.0, None), ("key_passes", 3.0, None),
    ("progressive_passes", 1.0, 5), ("duels_won", 1.0, 5), ("interceptions", 1.0, 5), ("passes_completed", 0.1, 30),
)
TOP_PLAYERS = 3
TEAM_KEYS = ("shots", "xg", "goals", "box_entries", "pass_accuracy", "possession")

LABELS: dict[str, dict[str, tuple[str, str]]] = {
    "goals": {"en": ("goal", "goals"), "fr": ("but", "buts"), "es": ("gol", "goles")},
    "assists": {"en": ("assist", "assists"), "fr": ("passe décisive", "passes décisives"),
                "es": ("asistencia", "asistencias")},
    "xg": {"en": ("xG", "xG"), "fr": ("xG", "xG"), "es": ("xG", "xG")},
    "key_passes": {"en": ("key pass", "key passes"), "fr": ("passe clé", "passes clés"),
                   "es": ("pase clave", "pases clave")},
    "progressive_passes": {"en": ("forward pass", "forward passes"),
                           "fr": ("passe vers l'avant", "passes vers l'avant"),
                           "es": ("pase hacia delante", "pases hacia delante")},
    "duels_won": {"en": ("duel won", "duels won"), "fr": ("duel gagné", "duels gagnés"),
                  "es": ("duelo ganado", "duelos ganados")},
    "interceptions": {"en": ("interception", "interceptions"), "fr": ("interception", "interceptions"),
                      "es": ("intercepción", "intercepciones")},
    "passes_completed": {"en": ("completed pass", "completed passes"), "fr": ("passe réussie", "passes réussies"),
                         "es": ("pase completado", "pases completados")},
    "shots": {"en": ("shot", "shots"), "fr": ("tir", "tirs"), "es": ("tiro", "tiros")},
}
AND = {"en": "and", "fr": "et", "es": "y"}
TEAM_LINE = {
    "away": {"en": "{team}: {shots} and {xg} xG while you were away, after {shots_b} and {xg_b} xG before.",
             "fr": "{team} : {shots} et {xg} xG pendant ton absence, après {shots_b} et {xg_b} xG avant.",
             "es": "{team}: {shots} y {xg} xG mientras no estabas, tras {shots_b} y {xg_b} xG antes."},
    "late": {"en": "{team}: {shots}, {xg} xG and {possession}% of the ball so far.",
             "fr": "{team} : {shots}, {xg} xG et {possession} % de possession jusqu'ici.",
             "es": "{team}: {shots}, {xg} xG y {possession} % de posesión hasta ahora."},
}


def window_state(meta: dict[str, Any], events: list[dict[str, Any]], from_t: float, to_t: float) -> MatchState:
    """The engine's statistics for the events of ``[from_t, to_t]`` only."""
    state = MatchState(meta)
    for e in events:
        if from_t <= e["t"] <= to_t and e["type"] != "match_start":
            state.apply(e)
    return state


def influence(p: PlayerStats) -> tuple[float, list[tuple[str, float]]]:
    """Influence score of a player's window, and the (stat, value) terms behind it, largest first."""
    terms = [(key, getattr(p, key), weight * (getattr(p, key) if cap is None else min(getattr(p, key), cap)))
             for key, weight, cap in INFLUENCE]
    score = sum(c for _, _, c in terms)
    reasons = [(key, round(value, 2)) for key, value, c in sorted(terms, key=lambda x: -x[2]) if c > 0][:3]
    return round(score, 1), reasons


def _decimal(value: float, lang: str) -> str:
    text = f"{value:.2f}"
    return text if lang == "en" else text.replace(".", ",")


def _count(key: str, value: float, lang: str) -> str:
    if key == "xg":
        return f"{_decimal(value, lang)} xG"
    one, many = LABELS[key][lang]
    singular = value <= 1 if lang == "fr" else value == 1      # French: "0 tir", "1 tir"
    return f"{int(value)} {one if singular else many}"


def _join(parts: list[str], lang: str) -> str:
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} {AND[lang]} {parts[-1]}"


def player_line(name: str, reasons: list[tuple[str, float]], lang: str) -> str:
    """Factual template: "Ciro Oakenfold: 1 goal, 0.31 xG and 2 key passes." in the fan's language."""
    sep = " : " if lang == "fr" else ": "
    return f"{name}{sep}{_join([_count(k, v, lang) for k, v in reasons], lang)}."


def team_line(name: str, window: dict[str, Any], before: dict[str, Any] | None, lang: str) -> str:
    """Factual template comparing the window with the match before the fan left."""
    if before is None:
        return TEAM_LINE["late"][lang].format(team=name, shots=_count("shots", window["shots"], lang),
                                              xg=_decimal(window["xg"], lang),
                                              possession=round(window["possession"] * 100))
    return TEAM_LINE["away"][lang].format(
        team=name, shots=_count("shots", window["shots"], lang), xg=_decimal(window["xg"], lang),
        shots_b=_count("shots", before["shots"], lang), xg_b=_decimal(before["xg"], lang))


def _team_window(state: MatchState, code: str) -> dict[str, Any]:
    t = state.teams[code].to_dict()
    total = sum(s.possession_s for s in state.teams.values())
    t["possession"] = round(state.teams[code].possession_s / total, 3) if total else 0.5
    return {k: t[k] for k in TEAM_KEYS}


def _team_view(snapshot: dict[str, Any], code: str) -> dict[str, Any]:
    t = snapshot["teams"][code]
    return {"shots": t["shots"], "xg": t["xg"], "possession": t["possession"], "danger": round(t["danger"]),
            "control": t["control"], "score": snapshot["score_str"], "players_on_pitch": t["players_on_pitch"],
            "pass_accuracy": t["pass_accuracy"], "box_entries": t["box_entries"]}


def what_you_missed(meta: dict[str, Any], events: list[dict[str, Any]], live: MatchState, from_t: float,
                    to_t: float, left: dict[str, Any] | None, now: dict[str, Any], lang: str) -> dict[str, Any]:
    """The return screen's data: top players of the window, both teams then vs now, template lines.

    ``left`` / ``now`` are engine snapshots when the fan left (``None`` for a late join) and
    came back; ``live`` is the match state at return (whole-match player stats).
    """
    win = window_state(meta, events, from_t, to_t)
    ranked = []
    for pid, stats in win.players.items():
        score, reasons = influence(stats)
        if score > 0:
            ranked.append((score, pid, reasons))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    players = []
    for score, pid, reasons in ranked[:TOP_PLAYERS]:
        info = win.roster[pid]
        players.append({
            "id": pid, "name": info["name"], "number": info["number"], "position": info["position"],
            "team": info["team"], "influence": score, "reasons": reasons,
            "window": win.players[pid].to_dict(), "match": live.players[pid].to_dict(),
        })
    teams = {}
    for code in (win.home, win.away):
        window = _team_window(win, code)
        before = _team_view(left, code) if left else None
        teams[code] = {"name": win.team_names[code], "window": window, "before": before, "now": _team_view(now, code)}
    lines = {p["id"]: player_line(p["name"], [tuple(r) for r in p["reasons"]], lang) for p in players}
    lines |= {code: team_line(t["name"], t["window"], t["before"], lang) for code, t in teams.items()}
    minute = lambda snap: snap["minute"] if snap else 0  # noqa: E731
    return {
        "from_t": from_t, "to_t": to_t, "from_minute": minute(left), "to_minute": now["minute"],
        "late_join": left is None, "language": lang, "players": players, "teams": teams,
        "lines": lines, "source": "template",
    }
