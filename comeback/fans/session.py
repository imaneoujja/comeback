"""A fan's viewing session: present or away, and since when."""

from dataclasses import dataclass, field
from typing import Any

from comeback.fans.profiles import FanProfile


@dataclass
class FanSession:
    """Viewing state of one fan during one match (times are match ``t`` seconds)."""

    profile: FanProfile
    present: bool = True
    away_since: float | None = None
    joined_at: float = 0.0
    alerts_this_absence: int = 0
    notifications: list[dict[str, Any]] = field(default_factory=list)

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
