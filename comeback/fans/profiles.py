"""Fan profiles: club, favourite player, level, language, focus metric."""

import functools
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

PROFILES_PATH = Path(__file__).resolve().parents[2] / "data" / "profiles.json"
DEMO_MATCH = Path(__file__).resolve().parents[2] / "data" / "matches" / "demo-comeback.jsonl"


@dataclass(frozen=True)
class FanProfile:
    """Who the fan is and how they like their football told."""

    id: str
    name: str
    club_id: str | None
    favourite_player_id: str | None
    level: Literal["casual", "analyst"]
    language: Literal["en", "fr", "es"]
    focus_metric: str | None = None

    def relevant_teams(self, home: str, away: str) -> list[str]:
        """Teams whose danger matters to this fan: both — their side attacking *or* defending."""
        return [home, away]

    def pov_team(self) -> str | None:
        """The side this fan's story is told from: their club, or their favourite player's team."""
        if self.club_id:
            return self.club_id
        return self.favourite_player_id.split("-")[0] if self.favourite_player_id else None


def load_profiles(path: Path = PROFILES_PATH) -> dict[str, FanProfile]:
    """Profiles by id."""
    return {p["id"]: FanProfile(**p) for p in json.loads(path.read_text(encoding="utf-8"))}


@functools.cache
def _demo_sides() -> tuple[str, str]:
    """(home, away) club ids of the demo fixture the demo profiles were written for."""
    with DEMO_MATCH.open(encoding="utf-8") as f:
        meta = json.loads(f.readline())
    return meta["home"]["id"], meta["away"]["id"]


def for_match(profile: FanProfile, home: str, away: str) -> FanProfile:
    """The same fan in another fixture: the demo's home supporter backs this match's home club, the
    away supporter its away club, and a player-follower follows the same shirt number on that side."""
    demo_home, demo_away = _demo_sides()
    side = {demo_home: home, demo_away: away}
    club = profile.club_id if profile.club_id in (home, away, None) else side.get(profile.club_id, home)
    fav = profile.favourite_player_id
    if fav and fav.split("-")[0] not in (home, away):
        team, number = fav.split("-")
        fav = f"{side.get(team, away)}-{number}"
    return replace(profile, club_id=club, favourite_player_id=fav)
