"""Catch-up selection: which moments a returning fan needs, and what changed.

Length adapts to the absence: < 3 min → one line; 3-20 min → the 2-3 key moments;
> 20 min or a late join → the full story so far.
"""

from typing import Any, Literal

from comeback.fans.profiles import FanProfile

Bucket = Literal["line", "key_moments", "full_story"]
LINE_MAX_S = 180.0
KEY_MOMENTS_MAX_S = 1200.0
TOP_N: dict[str, int] = {"line": 1, "key_moments": 3, "full_story": 6}
MINOR_TYPES = {"danger_peak", "milestone", "substitution"}
CONTROL_GAP = 0.1


def length_bucket(away_s: float, late_join: bool = False) -> Bucket:
    """How much to tell, given how long the fan was gone."""
    if late_join or away_s > KEY_MOMENTS_MAX_S:
        return "full_story"
    if away_s >= LINE_MAX_S:
        return "key_moments"
    return "line"


def relevance(card: dict[str, Any], profile: FanProfile) -> float:
    """How much a moment matters to this particular fan."""
    score = 1.0
    if profile.club_id and card.get("team") == profile.club_id:
        score *= 1.2
    if profile.favourite_player_id and profile.favourite_player_id in card.get("players", []):
        score *= 1.6
    return score


def select_cards(cards: list[dict[str, Any]], from_t: float, to_t: float,
                 profile: FanProfile, bucket: Bucket) -> list[dict[str, Any]]:
    """Top moments of the window for this fan, in chronological order."""
    candidates = [
        c for c in cards
        if from_t <= c["t"] <= to_t
        and (c["type"] not in MINOR_TYPES or profile.favourite_player_id in c.get("players", []))
    ]
    swings = [c for c in candidates if c["type"] == "momentum_swing"]
    candidates = [c for c in candidates if c["type"] != "momentum_swing"] + swings[-1:]  # latest swing only
    ranked = sorted(candidates, key=lambda c: c["importance"] * relevance(c, profile), reverse=True)
    return sorted(ranked[: TOP_N[bucket]], key=lambda c: c["t"])


def _timeline_at(timeline: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    before = [entry for entry in timeline if entry["t"] <= t]
    return before[-1] if before else None


def _in_control(control: dict[str, float] | None, team_names: dict[str, str]) -> str | None:
    if not control:
        return None
    (a, ca), (b, cb) = control.items()
    if abs(ca - cb) < CONTROL_GAP:
        return "balanced"
    return team_names[a] if ca > cb else team_names[b]


def build_delta(timeline: list[dict[str, Any]], snapshot: dict[str, Any], from_t: float,
                team_names: dict[str, str], cards_in_window: list[dict[str, Any]]) -> dict[str, Any]:
    """What changed between ``from_t`` and now: score, control, numbers on the pitch, shape."""
    then = _timeline_at(timeline, from_t)
    control_now = {code: team["control"] for code, team in snapshot["teams"].items()}
    delta: dict[str, Any] = {
        "away_minutes": max(0, round((snapshot["t"] - from_t) / 60)),
        "minute_then": then["minute"] if then else 0,
        "minute_now": snapshot["minute"],
        "score_then": then["score"] if then else "0-0",
        "score_now": snapshot["score_str"],
        "in_control_then": _in_control(then["control"], team_names) if then else None,
        "in_control_now": _in_control(control_now, team_names),
    }
    on_pitch = {team_names[code]: team["players_on_pitch"] for code, team in snapshot["teams"].items()}
    if len(set(on_pitch.values())) > 1:
        delta["players_on_pitch_now"] = on_pitch
    changes = [c["type"] for c in cards_in_window if c["type"] in ("red_card", "shape_change", "penalty")]
    if changes:
        delta["key_changes"] = changes
    return delta
