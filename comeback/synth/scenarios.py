"""Scripted match scenarios: story "beats" injected into an otherwise simulated match.

Beats are recorded in the match metadata (``scenario``) so that the scripting is
transparent. Unscripted matches use no scenario at all.
"""

from dataclasses import dataclass
from typing import Literal

BeatKind = Literal["goal", "big_chance_missed", "red_card", "shape_change", "momentum"]


@dataclass(frozen=True)
class Beat:
    """One scripted event, fired when the match clock reaches ``minute``.

    Attributes:
        minute: Match-clock minute (second half starts at 45, 92 = 90+2).
        kind: What happens.
        team: Club code of the team the beat is about.
        player: Scorer / shooter / sent-off player / player substituted off.
        player_in: Incoming player for a ``shape_change``.
        until_minute: End of a ``momentum`` window.
        strength: Intensity of a ``momentum`` window (0-1).
        formation: New shape announced by a ``shape_change``.
        note: Human-readable description.
    """

    minute: float
    kind: BeatKind
    team: str
    player: str | None = None
    player_in: str | None = None
    until_minute: float | None = None
    strength: float = 1.0
    formation: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    """A scripted storyline for a fixture."""

    name: str
    description: str
    home: str
    away: str
    seed: int
    beats: tuple[Beat, ...]
    random_goals: bool = False
    random_substitutions: bool = False
    stoppage_minutes: tuple[int, int] | None = None


THE_COMEBACK = Scenario(
    name="The Comeback",
    description=(
        "Riverside Rovers trail Harbour Lights 0-2, change shape, exploit a red card "
        "and turn the match around in the last 20 minutes."
    ),
    home="RVR",
    away="HLT",
    seed=2026,
    beats=(
        Beat(18.3, "goal", "HLT", player="HLT-9", note="Lights strike first on the break"),
        Beat(39.2, "goal", "HLT", player="HLT-11", note="Lights double the lead before half-time"),
        Beat(55.0, "shape_change", "RVR", player="RVR-6", player_in="RVR-15", formation="4-2-4",
             note="Rovers sacrifice a holding midfielder for a second striker"),
        Beat(62.8, "red_card", "HLT", player="HLT-4", note="Lights centre-back sent off"),
        Beat(64.0, "momentum", "RVR", until_minute=71.5, strength=1.0,
             note="Rovers lay siege to the Lights box"),
        Beat(68.4, "big_chance_missed", "RVR", player="RVR-9", note="Rovers striker denied"),
        Beat(71.0, "goal", "RVR", player="RVR-9", note="The striker makes amends: 1-2"),
        Beat(72.0, "momentum", "RVR", until_minute=93.0, strength=0.6,
             note="Rovers keep pushing against ten men"),
        Beat(84.0, "goal", "RVR", player="RVR-15", note="The substitute equalises: 2-2"),
        Beat(92.0, "goal", "RVR", player="RVR-10", note="Stoppage-time winner: 3-2"),
    ),
    stoppage_minutes=(2, 5),
)

SCENARIOS: dict[str, Scenario] = {"demo-comeback": THE_COMEBACK}
