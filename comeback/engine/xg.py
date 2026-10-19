"""Expected-goals (xG) model shared by the simulator and the match engine."""

import math

GOAL_WIDTH_M = 7.32
PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0


def shot_geometry(x: float, y: float) -> tuple[float, float]:
    """Return (distance to goal centre in metres, goal-mouth angle in radians).

    Coordinates are in the shooting team's attacking frame (target goal at x = 105).
    """
    dx = max(0.1, PITCH_LENGTH_M - x)
    dy = y - PITCH_WIDTH_M / 2
    distance = math.hypot(dx, dy)
    half = GOAL_WIDTH_M / 2
    angle = math.atan2(GOAL_WIDTH_M * dx, dx * dx + dy * dy - half * half)
    if angle < 0:
        angle += math.pi
    return distance, angle


def expected_goals(distance_m: float, angle_rad: float, header: bool = False) -> float:
    """Logistic xG from shot distance and angle, clipped to [0.01, 0.85]."""
    z = -1.45 + 1.6 * angle_rad - 0.085 * distance_m - (0.9 if header else 0.0)
    xg = 1.0 / (1.0 + math.exp(-z))
    return max(0.01, min(0.85, xg))
