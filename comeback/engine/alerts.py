"""The "come back" alert rule: rising danger above a threshold, with a cooldown.

The rule is deterministic (no LLM): the Watcher agent uses it to decide, and
``scripts/evaluate_alerts.py`` uses it to measure precision and lead time. It
stays quiet right after the team's own shot: that chance is already over.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    """Thresholds of the alert rule.

    The threshold was tuned on unscripted matches (seeds 1001-1050) to announce at
    least half of the goals, and is reported on held-out matches (seeds 2001-2050).
    """

    threshold: float = 44.0
    min_slope: float = 3.0
    cooldown_s: float = 180.0
    quiet_after_shot_s: float = 20.0


class AlertTracker:
    """Applies an :class:`AlertRule` to one team's danger over time."""

    def __init__(self, rule: AlertRule | None = None) -> None:
        self.rule = rule or AlertRule()
        self.last_alert_t: float | None = None

    def check(self, t: float, danger: float, slope: float, since_shot_s: float) -> bool:
        """Return True (and arm the cooldown) if an alert should fire now."""
        rule = self.rule
        if danger < rule.threshold or slope < rule.min_slope or since_shot_s < rule.quiet_after_shot_s:
            return False
        if self.last_alert_t is not None and t - self.last_alert_t < rule.cooldown_s:
            return False
        self.last_alert_t = t
        return True
