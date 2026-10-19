"""Fan profiles: club, favourite player, level, language, focus metric."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROFILES_PATH = Path(__file__).resolve().parents[2] / "data" / "profiles.json"


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
