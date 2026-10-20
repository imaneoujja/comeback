"""Deterministic fallback texts (en / fr / es), built only from verified facts.

Used when the LLM is offline, rate-limited, over budget, times out, or when the
Verifier rejects a draft twice. Output is flagged ``source: "template"``.
"""

from typing import Any

LANGUAGES = ("en", "fr", "es")

# Moment one-liners, keyed by type (goal: by situation). Placeholders are filled
# from the moment facts plus {team}, {opponent}, {minute}, {player}.
_MOMENT_LINES: dict[str, dict[str, str]] = {
    "goal.opener": {
        "en": "{minute}' — {scorer_name} opens the scoring for {team}: {score_after}.",
        "fr": "{minute}e — {scorer_name} ouvre le score pour {team} : {score_after}.",
        "es": "Min. {minute} — {scorer_name} abre el marcador para {team}: {score_after}.",
    },
    "goal.equaliser": {
        "en": "{minute}' — {scorer_name} equalises for {team}: {score_after}.",
        "fr": "{minute}e — {scorer_name} égalise pour {team} : {score_after}.",
        "es": "Min. {minute} — {scorer_name} empata para {team}: {score_after}.",
    },
    "goal.go_ahead": {
        "en": "{minute}' — {scorer_name} puts {team} ahead: {score_after}.",
        "fr": "{minute}e — {scorer_name} donne l'avantage à {team} : {score_after}.",
        "es": "Min. {minute} — {scorer_name} pone por delante a {team}: {score_after}.",
    },
    "goal.pulls_one_back": {
        "en": "{minute}' — {scorer_name} pulls one back for {team}: {score_after}.",
        "fr": "{minute}e — {scorer_name} réduit l'écart pour {team} : {score_after}.",
        "es": "Min. {minute} — {scorer_name} recorta distancias para {team}: {score_after}.",
    },
    "goal.extends_lead": {
        "en": "{minute}' — {scorer_name} extends {team}'s lead: {score_after}.",
        "fr": "{minute}e — {scorer_name} creuse l'écart pour {team} : {score_after}.",
        "es": "Min. {minute} — {scorer_name} amplía la ventaja de {team}: {score_after}.",
    },
    "big_chance": {
        "en": "{minute}' — big chance for {player_name} ({team}), but it is {outcome_text}.",
        "fr": "{minute}e — grosse occasion pour {player_name} ({team}), mais {outcome_text}.",
        "es": "Min. {minute} — gran ocasión de {player_name} ({team}), pero {outcome_text}.",
    },
    "red_card": {
        "en": "{minute}' — red card for {player_name}: {team} down to {players_left} men.",
        "fr": "{minute}e — carton rouge pour {player_name} : {team} réduit à {players_left}.",
        "es": "Min. {minute} — roja para {player_name}: {team} se queda con {players_left}.",
    },
    "penalty": {
        "en": "{minute}' — penalty to {team} after a foul on {fouled_player_name}.",
        "fr": "{minute}e — penalty pour {team} après une faute sur {fouled_player_name}.",
        "es": "Min. {minute} — penalti para {team} tras falta sobre {fouled_player_name}.",
    },
    "shape_change": {
        "en": "{minute}' — {team} switch to a {formation}: {player_in_name} on for {player_out_name}.",
        "fr": "{minute}e — {team} passe en {formation} : {player_in_name} remplace {player_out_name}.",
        "es": "Min. {minute} — {team} cambia a un {formation}: entra {player_in_name} por {player_out_name}.",
    },
    "substitution": {
        "en": "{minute}' — {team}: {player_in_name} on for {player_out_name}.",
        "fr": "{minute}e — {team} : {player_in_name} remplace {player_out_name}.",
        "es": "Min. {minute} — {team}: entra {player_in_name} por {player_out_name}.",
    },
    "momentum_swing": {
        "en": "{minute}' — the game turns: {team} take control.",
        "fr": "{minute}e — le match bascule : {team} prend le contrôle.",
        "es": "Min. {minute} — el partido cambia: {team} toma el control.",
    },
    "danger_peak": {
        "en": "{minute}' — {team} pile on the pressure: {box_entries} box entries in 2 minutes.",
        "fr": "{minute}e — {team} pousse fort : {box_entries} entrées dans la surface en 2 minutes.",
        "es": "Min. {minute} — {team} aprieta: {box_entries} llegadas al área en 2 minutos.",
    },
    "milestone": {
        "en": "{minute}' — milestone for {player_name} ({team}).",
        "fr": "{minute}e — cap franchi pour {player_name} ({team}).",
        "es": "Min. {minute} — hito para {player_name} ({team}).",
    },
    "half_time": {
        "en": "Half-time: {score}.",
        "fr": "Mi-temps : {score}.",
        "es": "Descanso: {score}.",
    },
    "full_time": {
        "en": "Full-time: {score}.",
        "fr": "Fin du match : {score}.",
        "es": "Final: {score}.",
    },
}

_OUTCOME_TEXT = {
    "saved": {"en": "saved", "fr": "le gardien l'arrête", "es": "la para el portero"},
    "blocked": {"en": "blocked", "fr": "le tir est contré", "es": "el tiro es bloqueado"},
    "off_target": {"en": "off target", "fr": "c'est à côté", "es": "se va fuera"},
}

_WHY_EN: dict[str, str] = {
    "goal": "It changes the score to {score_after} with the {situation_text}.",
    "big_chance": "An xG of {xg} chance that did not go in: the score stays {score}.",
    "red_card": "{team} must play the rest of the match with {players_left} players.",
    "penalty": "A penalty is the best chance a team can get.",
    "shape_change": "{team} change their shape to {formation} while the score is {score}.",
    "momentum_swing": "Control of the ball and of the passing game has shifted to {team}.",
    "danger_peak": "{team} reached a danger index of {danger}.",
    "half_time": "The first half ends {score}.",
    "full_time": "The match ends {score}.",
}

_SITUATION_TEXT = {
    "opener": "opening goal", "equaliser": "equaliser", "go_ahead": "go-ahead goal",
    "pulls_one_back": "goal that pulls one back", "extends_lead": "goal that extends the lead",
}

ALERT_TEXT: dict[str, dict[str, str]] = {
    "attacking": {
        "en": "Come back — {team} have {box_text} in 2 minutes{shots_text}{side_text}.",
        "fr": "Reviens — {team} {box_text} en 2 minutes{shots_text}{side_text}.",
        "es": "Vuelve — {team} {box_text} en 2 minutos{shots_text}{side_text}.",
    },
    "defending": {
        "en": "Come back — {team} are under siege: {opponent} have {box_text} in 2 minutes{shots_text}.",
        "fr": "Reviens — {team} est assiégé : {opponent} {box_text} en 2 minutes{shots_text}.",
        "es": "Vuelve — {team} está contra las cuerdas: {opponent} {box_text} en 2 minutos{shots_text}.",
    },
}

# (no box entry, one, several) — {n} is the number of box entries
BOX_TEXT = {
    "en": ("piled on the pressure", "entered the box once", "entered the box {n} times"),
    "fr": ("met la pression", "est entré une fois dans la surface", "est entré {n} fois dans la surface"),
    "es": ("aprieta sin parar", "ha pisado el área una vez", "ha pisado el área {n} veces"),
}

# (one shot, several) — {n} is the number of shots
SHOTS_TEXT = {
    "en": (" and taken {n} shot", " and taken {n} shots"),
    "fr": (" et a tenté {n} tir", " et a tenté {n} tirs"),
    "es": (" y ha rematado {n} vez", " y ha rematado {n} veces"),
}


def pressure_texts(lang: str, box_entries: int, shots: int) -> dict[str, str]:
    """Grammatical "box entries" and "shots" fragments for alert texts."""
    box = BOX_TEXT[lang][min(box_entries, 2)].format(n=box_entries)
    shots_text = SHOTS_TEXT[lang][0 if shots == 1 else 1].format(n=shots) if shots else ""
    return {"box_text": box, "shots_text": shots_text}


SIDE_TEXT = {
    "en": ", {opponent}'s {side} side is cracking",
    "fr": ", le côté {side} de {opponent} craque",
    "es": ", la banda {side} de {opponent} se resquebraja",
}

SIDE_WORDS = {
    "left": {"en": "left", "fr": "gauche", "es": "izquierda"},
    "right": {"en": "right", "fr": "droit", "es": "derecha"},
}

GOAL_ALERT_TEXT = {
    "en": "Goal! {scorer_name} ({minute}') — {home} {score} {away}.",
    "fr": "But ! {scorer_name} ({minute}e) — {home} {score} {away}.",
    "es": "¡Gol! {scorer_name} (min. {minute}) — {home} {score} {away}.",
}

CALLED_IT_TEXT = {  # a goal that came after a call-back, with the fan back in time
    "en": "COMEBACK called it: alert at {alert_minute}', goal at {minute}'. You were back in time.",
    "fr": "COMEBACK l'avait senti : alerte à la {alert_minute}e, but à la {minute}e. Tu étais là à temps.",
    "es": "COMEBACK lo vio venir: aviso en el {alert_minute}', gol en el {minute}'. Volviste a tiempo.",
}

CATCHUP_INTRO = {
    "en": "While you were away ({away_minutes} min): {score_then} → {score_now}.",
    "fr": "Pendant ton absence ({away_minutes} min) : {score_then} → {score_now}.",
    "es": "Mientras no estabas ({away_minutes} min): {score_then} → {score_now}.",
}

STORY_INTRO = {
    "en": "The story so far ({minute}'): {score_now}.",
    "fr": "L'histoire du match jusqu'ici ({minute}e) : {score_now}.",
    "es": "La historia hasta ahora (min. {minute}): {score_now}.",
}

FINAL_INTRO = {
    "en": "Full-time: {score_now}.",
    "fr": "Coup de sifflet final : {score_now}.",
    "es": "Final del partido: {score_now}.",
}

NOTHING_HAPPENED = {
    "en": "Nothing major happened — still {score_now}.",
    "fr": "Rien de majeur — toujours {score_now}.",
    "es": "Nada importante — sigue {score_now}.",
}


class _Defaults(dict):
    """format_map helper: unknown placeholders render as an empty string."""

    def __missing__(self, key: str) -> str:
        return ""


def moment_values(moment: dict[str, Any], team_names: dict[str, str]) -> dict[str, Any]:
    """Placeholder values for a moment: its facts plus readable team names."""
    team = moment.get("team")
    opponent = next((name for code, name in team_names.items() if code != team), "")
    values = {**moment["facts"], "minute": moment["minute"],
              "team": team_names.get(team, ""), "opponent": opponent}
    return values


def moment_line(moment: dict[str, Any], lang: str, team_names: dict[str, str]) -> str:
    """One-line description of a moment in ``lang``."""
    lang = lang if lang in LANGUAGES else "en"
    mtype = moment["type"]
    key = f"goal.{moment['facts'].get('situation')}" if mtype == "goal" else mtype
    values = moment_values(moment, team_names)
    if mtype == "big_chance":
        values["outcome_text"] = _OUTCOME_TEXT.get(values.get("outcome"), _OUTCOME_TEXT["saved"])[lang]
    return _MOMENT_LINES.get(key, _MOMENT_LINES["milestone"])[lang].format_map(_Defaults(values))


def moment_card_text(moment: dict[str, Any], team_names: dict[str, str]) -> dict[str, str]:
    """Fallback English headline and why-it-matters for a moment card."""
    values = moment_values(moment, team_names)
    values["situation_text"] = _SITUATION_TEXT.get(values.get("situation"), "goal")
    headline = moment_line(moment, "en", team_names).split(" — ", 1)[-1]
    headline = headline[:1].upper() + headline[1:]  # the line's tail starts lower case ("the game turns…")
    why = _WHY_EN.get(moment["type"], "A notable moment for {team}.").format_map(_Defaults(values))
    return {"headline": headline, "why_it_matters": why}
