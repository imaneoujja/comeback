"""Pitch geometry helpers (105 x 68 m, home attacks towards x = 105 in both halves)."""

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
FINAL_THIRD_X = PITCH_LENGTH * 2 / 3
BOX_DEPTH = 16.5
BOX_HALF_WIDTH = 20.16


def attacking_frame(x: float, y: float, is_home: bool) -> tuple[float, float]:
    """Convert absolute coordinates to a team's attacking frame (target goal at x = 105)."""
    return (x, y) if is_home else (PITCH_LENGTH - x, PITCH_WIDTH - y)


def in_box(ax: float, ay: float) -> bool:
    """Whether an attacking-frame point is inside the opponent penalty box."""
    return ax >= PITCH_LENGTH - BOX_DEPTH and abs(ay - PITCH_WIDTH / 2) <= BOX_HALF_WIDTH


def in_final_third(ax: float) -> bool:
    """Whether an attacking-frame point is in the attacking third."""
    return ax >= FINAL_THIRD_X


def channel(ay: float) -> str:
    """Attacking channel ("left", "centre", "right") seen from the attacking team."""
    if ay > PITCH_WIDTH * 2 / 3:
        return "left"
    if ay < PITCH_WIDTH / 3:
        return "right"
    return "centre"
