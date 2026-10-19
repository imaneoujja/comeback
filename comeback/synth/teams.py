"""Fictional clubs and deterministic team generation for synthetic matches."""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Club:
    """Metadata and playing identity for a fictional club."""

    id: str
    name: str
    colour: str
    play_style: str
    strength: int


@dataclass(frozen=True)
class Player:
    """A fictional player with core football attributes."""

    id: str
    number: int
    name: str
    position: str
    passing: int
    pace: int
    finishing: int
    defending: int
    top_speed_kmh: float


@dataclass(frozen=True)
class Team:
    """A club squad with a 4-3-3 starting XI and four substitutes."""

    club: Club
    starting_xi: tuple[Player, ...]
    bench: tuple[Player, ...]

    @property
    def players(self) -> tuple[Player, ...]:
        """All squad players, starters first."""
        return self.starting_xi + self.bench


# Club ids are the three-letter codes used in events ("team": "EMB").
# play_style must be a key of comeback.synth.simulator.STYLES.
CLUBS: dict[str, Club] = {
    club.id: club
    for club in (
        Club("EMB", "Emberfield", "#EE7B30", "possession", 78),
        Club("SMC", "Saltmarsh Comets", "#1FA39A", "direct", 75),
        Club("LKA", "Larkhaven Athletic", "#2F6B4F", "pressing", 73),
        Club("THU", "Thornwick United", "#6B7480", "balanced", 70),
        Club("CBC", "Calderbay City", "#E56B6F", "counter", 72),
        Club("AVW", "Ashvale Wanderers", "#B58BD4", "low_block", 68),
    )
}

FIRST_NAMES: tuple[str, ...] = (
    "Aven", "Bren", "Ciro", "Daro", "Elian", "Fenn", "Galen", "Halen",
    "Ivo", "Jalen", "Kiro", "Lio", "Maren", "Nilo", "Oren", "Perrin",
    "Quin", "Riven", "Soren", "Tavi", "Ulan", "Vero", "Wren", "Yori",
)

LAST_NAMES: tuple[str, ...] = (
    "Ashcombe", "Bellmere", "Caulder", "Dunlow", "Elderglen", "Farrow",
    "Glenwick", "Harthill", "Iverstone", "Jarrow", "Kestrel", "Larkspur",
    "Merewood", "Northcott", "Oakenfold", "Pinewell", "Quarryn", "Rookwell",
    "Sableford", "Thornby", "Umberley", "Vellum", "Westlin", "Yarrowby",
    "Brackwell", "Corrigan", "Delamere", "Fenwright", "Galloway", "Hollins",
    "Kilbride", "Lockhart", "Moorcroft", "Penhallow", "Ravensworth", "Tremayne",
)

_STARTING_XI: tuple[tuple[int, str], ...] = (
    (1, "GK"),
    (2, "RB"),
    (4, "CB"),
    (5, "CB"),
    (3, "LB"),
    (6, "CDM"),
    (8, "CM"),
    (10, "CAM"),
    (7, "RW"),
    (9, "ST"),
    (11, "LW"),
)

_BENCH_POSITIONS: tuple[str, ...] = ("GK", "DF", "MF", "FW")

# Base 4-3-3 spots by shirt number, in the team's attacking frame:
# own goal at x = 0, opponent goal at x = 105; y = 0 is the team's right touchline.
FORMATION_433: dict[int, tuple[float, float]] = {
    1: (5.0, 34.0),
    2: (30.0, 8.0),
    4: (24.0, 25.0),
    5: (24.0, 43.0),
    3: (30.0, 60.0),
    6: (40.0, 34.0),
    8: (52.0, 22.0),
    10: (56.0, 46.0),
    7: (74.0, 10.0),
    9: (80.0, 34.0),
    11: (74.0, 58.0),
}

_ATTRIBUTE_PROFILES: dict[str, tuple[int, int, int, int, float]] = {
    "GK": (48, 42, 18, 78, 28.0),
    "RB": (57, 70, 35, 70, 34.0),
    "LB": (58, 71, 36, 69, 34.5),
    "CB": (55, 58, 30, 78, 32.0),
    "CDM": (68, 63, 43, 72, 32.5),
    "CM": (73, 68, 55, 62, 33.5),
    "CAM": (76, 70, 66, 45, 34.0),
    "RW": (63, 81, 70, 38, 36.0),
    "ST": (60, 76, 79, 35, 35.0),
    "LW": (64, 82, 72, 39, 36.5),
    "DF": (57, 64, 34, 74, 33.0),
    "MF": (70, 67, 54, 61, 33.0),
    "FW": (62, 78, 73, 38, 35.5),
}


def _build_player(
    club: Club,
    jersey_number: int,
    position: str,
    name: str,
    rng: random.Random,
) -> Player:
    """Build one player using role-based attributes and seeded variation."""
    passing, pace, finishing, defending, top_speed = _ATTRIBUTE_PROFILES[position]
    strength_adjustment = round((club.strength - 70) * 0.35)

    def rating(base: int) -> int:
        return max(20, min(95, base + strength_adjustment + rng.randint(-7, 7)))

    speed_adjustment = strength_adjustment * 0.12 + rng.uniform(-1.2, 1.2)
    return Player(
        id=f"{club.id}-{jersey_number}",
        number=jersey_number,
        name=name,
        position=position,
        passing=rating(passing),
        pace=rating(pace),
        finishing=rating(finishing),
        defending=rating(defending),
        top_speed_kmh=round(max(24.0, min(38.0, top_speed + speed_adjustment)), 1),
    )


def build_team(club_id: str, seed: int, exclude_surnames: frozenset[str] = frozenset()) -> Team:
    """Build a deterministic 4-3-3 squad for a known fictional club.

    The same club, seed and exclusions always produce the same players and
    ratings. The starting XI is ordered by shirt number, with four substitutes
    (numbers 12-15) listed after.

    Args:
        club_id: Three-letter code of one of the clubs in :data:`CLUBS`.
        seed: Seed for the local random generator.
        exclude_surnames: Surnames already used (e.g. by the opponent): every player
            in a match has a unique surname, so commentary never confuses two players.

    Raises:
        ValueError: If ``club_id`` does not identify a known club.
    """
    try:
        club = CLUBS[club_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown club_id {club_id!r}; expected one of {', '.join(CLUBS)}."
        ) from exc

    rng = random.Random(f"{seed}:{club_id}")
    squad_size = len(_STARTING_XI) + len(_BENCH_POSITIONS)
    surnames = rng.sample([s for s in LAST_NAMES if s not in exclude_surnames], squad_size)
    selected_names = [f"{rng.choice(FIRST_NAMES)} {surname}" for surname in surnames]

    starters = tuple(
        _build_player(club, number, position, selected_names[index], rng)
        for index, (number, position) in enumerate(_STARTING_XI)
    )
    bench = tuple(
        _build_player(
            club,
            12 + index,
            position,
            selected_names[len(_STARTING_XI) + index],
            rng,
        )
        for index, position in enumerate(_BENCH_POSITIONS)
    )
    return Team(club=club, starting_xi=starters, bench=bench)


def build_fixture(home_id: str, away_id: str, seed: int) -> tuple[Team, Team]:
    """Build both squads of a match: every surname is unique across the two teams."""
    home = build_team(home_id, seed)
    away = build_team(away_id, seed, exclude_surnames=frozenset(p.name.split()[-1] for p in home.players))
    return home, away
