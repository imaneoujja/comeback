"""Danger index: how close a team is to creating a real chance, right now.

Each attacking action adds a weighted contribution that decays exponentially
(time constant ~60 s, so actions older than ~2 minutes barely count). The sum
is squashed with tanh into a 0-100 index.
"""

import math
from collections import Counter, deque
from dataclasses import dataclass

WEIGHTS: dict[str, float] = {
    "box_entry": 8.0,
    "final_third_pass": 2.0,
    "corner": 6.0,
    "ball_won_high": 5.0,
    "pressure_won": 2.0,
    "opp_half_pass": 0.6,      # territorial pressure: sustained possession in the opponent half
}
SHOT_BASE = 10.0
SHOT_XG_WEIGHT = 40.0
TAU_S = 60.0
SCALE = 55.0
REASON_WINDOW_S = 120.0
_MEMORY_S = 360.0


def shot_weight(xg: float) -> float:
    """Danger weight of a shot."""
    return SHOT_BASE + SHOT_XG_WEIGHT * xg


@dataclass(frozen=True)
class Contribution:
    """One attacking action that raised a team's danger."""

    t: float
    kind: str
    weight: float
    channel: str | None = None
    event_id: str | None = None


class DangerTracker:
    """Danger index of one team, queryable at any time."""

    def __init__(self) -> None:
        self._items: deque[Contribution] = deque()

    def add(self, contribution: Contribution) -> None:
        """Record an action and forget the ones too old to matter."""
        self._items.append(contribution)
        while self._items and contribution.t - self._items[0].t > _MEMORY_S:
            self._items.popleft()

    def raw(self, t: float) -> float:
        """Decayed sum of contributions at time ``t``."""
        return sum(c.weight * math.exp(-(t - c.t) / TAU_S) for c in self._items if c.t <= t)

    def value(self, t: float) -> float:
        """Danger index (0-100) at time ``t``."""
        return 100.0 * math.tanh(self.raw(t) / SCALE)

    def slope(self, t: float, lookback_s: float = 30.0) -> float:
        """Change of the index over the last ``lookback_s`` seconds (positive = rising)."""
        return self.value(t) - self.value(t - lookback_s)

    def reasons(self, t: float, window_s: float = REASON_WINDOW_S) -> dict[str, object]:
        """Facts behind the current danger: counts per action type and main attacking channel."""
        recent = [c for c in self._items if t - window_s <= c.t <= t]
        counts = Counter(c.kind for c in recent)
        channels = Counter(c.channel for c in recent if c.kind == "box_entry" and c.channel)
        main = channels.most_common(1)[0][0] if channels else None
        return {
            "window_s": int(window_s),
            "box_entries": counts["box_entry"],
            "shots": counts["shot"],
            "corners": counts["corner"],
            "balls_won_high": counts["ball_won_high"],
            "final_third_passes": counts["final_third_pass"],
            "main_channel": main,
            "evidence_event_ids": [c.event_id for c in recent if c.event_id and c.kind in ("box_entry", "shot")][-6:],
        }
