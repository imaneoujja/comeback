"""Pass quality model shared by the simulator and the match engine."""

import math


def pass_difficulty(
    distance_m: float,
    under_pressure: bool,
    forward_ratio: float,
    into_final_third: bool,
) -> float:
    """Pass difficulty rating from 0 (trivial) to 100 (near impossible).

    Args:
        distance_m: Pass length in metres.
        under_pressure: Whether the passer was being pressed.
        forward_ratio: Share of the pass travelling towards the opponent goal (0-1).
        into_final_third: Whether the pass ends in the attacking third.
    """
    score = (
        10.0
        + 1.1 * distance_m
        + 25.0 * under_pressure
        + 12.0 * forward_ratio
        + 10.0 * into_final_third
        + 8.0 * (distance_m > 35.0)
    )
    return max(0.0, min(100.0, score))


def completion_probability(passing_rating: float, difficulty: float, team_mod: float = 0.0) -> float:
    """Probability that a pass of the given difficulty is completed."""
    return 1.0 / (1.0 + math.exp(-((passing_rating - difficulty) / 10.0 + team_mod)))
