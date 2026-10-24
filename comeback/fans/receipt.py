"""The fan's full-time receipt: how much of the match they lived live, and what their alerts were worth.

"You were live for N of M goals, and caught up on the rest in X seconds." Goals count from the
moment the fan started following the match (a skipped stretch is neither live nor caught up);
a goal is live when the fan was present, caught up when it fell in an absence or before a late
join. Alerts are judged with the same definitions as the README and ``scripts/evaluate_alerts.py``
(``comeback/engine/alerts.py``). The seconds spent catching up are measured by the screen.
"""

from typing import Any

from comeback.engine.alerts import ANTICIPATION_S, CHANCE_HORIZON_S, CHANCE_MIN_XG


def _inside(t: float, bands: list[tuple[float, float]]) -> bool:
    return any(start <= t <= end for start, end in bands)


def _total(bands: list[tuple[float, float]]) -> float:
    return sum(max(0.0, end - start) for start, end in bands)


def match_receipt(events: list[dict[str, Any]], notifications: list[dict[str, Any]],
                  away_bands: list[dict[str, Any]], skipped: list[tuple[float, float]], end_t: float) -> dict[str, Any]:
    """Real numbers for the receipt, from the events of the match and this fan's own history."""
    away = [(b["from_t"], b["to_t"] if b["to_t"] is not None else end_t) for b in away_bands]
    goals = [e for e in events if e["type"] == "goal" and not _inside(e["t"], skipped)]
    live = [g for g in goals if not _inside(g["t"], away)]
    shots = [e for e in events if e["type"] == "shot" and e["xg"] >= CHANCE_MIN_XG]
    alerts = [n for n in notifications if n["kind"] == "come_back"]
    came_true = [a for a in alerts if any(s["team"] == a["team"] and 0 < s["t"] - a["t"] <= CHANCE_HORIZON_S
                                          for s in shots)]
    announced = [g for g in goals if any(a["team"] == g["team"] and 0 < g["t"] - a["t"] <= ANTICIPATION_S
                                         for a in alerts)]
    followed_s = end_t - _total(skipped)
    absences = [(b["from_t"], b["to_t"] if b["to_t"] is not None else end_t)
                for b in away_bands if not b.get("late_join")]
    return {
        "goals": len(goals), "goals_live": len(live), "goals_caught_up": len(goals) - len(live),
        "minutes_followed": round(followed_s / 60), "minutes_live": round((followed_s - _total(away)) / 60),
        "absences": len(absences), "minutes_away": round(_total(absences) / 60),
        "late_join": any(b.get("late_join") for b in away_bands),
        "alerts": len(alerts), "alerts_came_true": len(came_true), "goals_announced": len(announced),
        "chance_horizon_s": CHANCE_HORIZON_S, "chance_min_xg": CHANCE_MIN_XG,
        "anticipation_min": round(ANTICIPATION_S / 60),
    }
