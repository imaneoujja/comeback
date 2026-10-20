"""A fan's viewing session: present or away, and since when."""

from dataclasses import dataclass, field
from typing import Any

from comeback.fans.profiles import FanProfile

ALERT_FOR = ("threat", "equaliser", "big")


@dataclass
class AlertSettings:
    """The fan's own rules for being called back (opt-in, changeable at any time).

    ``alert_for``: "threat" (a team is close to scoring — the default), "equaliser" (only when
    the fan's side is pushing for an equaliser or a winner), or "big" (threats plus red cards
    and penalties). ``spoilers``: show scores in notifications (off by default: "something big
    happened, your replay is ready"). ``night``: wake me only for the biggest moments — stricter
    threshold, one call per absence, after-the-fact notifications delivered silently.
    """

    alert_for: str = "threat"
    spoilers: bool = False
    night: bool = False


@dataclass
class FanSession:
    """Viewing state of one fan during one match (times are match ``t`` seconds)."""

    profile: FanProfile
    present: bool = True
    away_since: float | None = None
    joined_at: float = 0.0
    alerts_this_absence: int = 0
    notifications: list[dict[str, Any]] = field(default_factory=list)
    settings: AlertSettings = field(default_factory=AlertSettings)

    def go_away(self, t: float) -> None:
        if self.present:
            self.present, self.away_since, self.alerts_this_absence = False, t, 0

    def come_back(self, t: float) -> tuple[float, float] | None:
        """Mark the fan present; return the away window ``(from_t, to_t)`` if they were away."""
        if self.present or self.away_since is None:
            return None
        window = (self.away_since, t)
        self.present, self.away_since = True, None
        return window
