"""Timed, renderer-agnostic overlay cues a broadcast graphics engine could consume.

Cue format::

    {"cue_id", "t_in", "t_out", "layer": "lower_third|top_right|banner",
     "template": "player_tag|pass_quality|shot_speed|sprint|danger|moment",
     "data": {...}, "priority": 0-100, "audience": "all|analyst|casual"}
"""

import math
from typing import Any

from comeback.engine.moments import Moment
from comeback.engine.state import MatchState

PLAYER_TAG_GAP_S = 15.0
PASS_QUALITY_MIN = 65
PASS_QUALITY_ALL = 80
SPRINT_TAG_KMH = 32.0          # speed threshold for a speed tag
DISTANCE_TAG_STEP_M = 100.0    # distance threshold: every 100 m a player covers with the ball
_KEY_TAG_TYPES = {"shot", "goal", "card"}


def difficulty_label(difficulty: float) -> str:
    """Short broadcast label for a pass difficulty rating."""
    if difficulty >= 85:
        return "Elite"
    if difficulty >= 75:
        return "Hard"
    return "Tough"


class OverlayBuilder:
    """Turns events and moments into overlay cues."""

    def __init__(self, state: MatchState) -> None:
        self.state = state
        self.cues: list[dict[str, Any]] = []
        self._last_tag_t = -PLAYER_TAG_GAP_S
        self._last_tag_player: str | None = None

    def for_event(self, e: dict[str, Any], moments: list[Moment]) -> list[dict[str, Any]]:
        """Cues triggered by one event and the moments it produced."""
        new: list[dict[str, Any]] = []
        new += self._player_tag(e)
        if e["type"] == "pass" and e["success"] and e["difficulty"] >= PASS_QUALITY_MIN:
            new.append(self._cue(e["t"], 5, "top_right", "pass_quality", {
                "team": e["team"], "player": e["player"], "player_name": self.state.player_name(e["player"]),
                "receiver": e["receiver"], "receiver_name": self.state.player_name(e["receiver"]),
                "distance_m": e["distance_m"], "difficulty": e["difficulty"],
                "label": difficulty_label(e["difficulty"]), "ball_speed_kmh": e["ball_speed_kmh"],
            }, int(e["difficulty"] * 0.6), "all" if e["difficulty"] >= PASS_QUALITY_ALL else "analyst"))
        elif e["type"] == "shot":
            new.append(self._cue(e["t"], 5, "top_right", "shot_speed", {
                "team": e["team"], "player": e["player"], "player_name": self.state.player_name(e["player"]),
                "shot_speed_kmh": e["shot_speed_kmh"], "xg": e["xg"], "outcome": e["outcome"],
            }, 70, "all"))
        elif e["type"] == "sprint" and e["speed_kmh"] >= SPRINT_TAG_KMH:
            new.append(self._cue(e["t"], 4, "lower_third", "sprint", {
                **self._who(e["player"]), "speed_kmh": e["speed_kmh"], "distance_m": e["distance_m"],
                "distance_with_ball_m": round(self.state.players[e["player"]].distance_with_ball_m),
            }, 55, "all"))
        elif e["type"] == "carry":
            covered = self.state.players[e["player"]].distance_with_ball_m
            before = max(0.0, covered - math.dist((e["x"], e["y"]), (e["end_x"], e["end_y"])))
            step = DISTANCE_TAG_STEP_M
            if covered >= step and int(covered // step) > int(before // step):
                new.append(self._cue(e["t"], 4, "lower_third", "distance", {
                    **self._who(e["player"]), "distance_with_ball_m": round(covered),
                    "threshold_m": int(covered // DISTANCE_TAG_STEP_M * DISTANCE_TAG_STEP_M),
                    "top_speed_kmh": self.state.players[e["player"]].top_speed_kmh,
                }, 45, "all"))
        for m in moments:
            new.append(self._moment_cue(m))
        self.cues += new
        return new

    def _who(self, player: str) -> dict[str, Any]:
        info = self.state.roster[player]
        return {"team": info["team"], "player": player, "player_name": info["name"], "number": info["number"],
                "position": info["position"]}

    def _cue(self, t: float, duration: float, layer: str, template: str, data: dict[str, Any],
             priority: int, audience: str) -> dict[str, Any]:
        return {
            "cue_id": f"c{len(self.cues) + 1:05d}",
            "t_in": t, "t_out": round(t + duration, 1), "layer": layer, "template": template,
            "data": data, "priority": max(0, min(100, priority)), "audience": audience,
        }

    def _player_tag(self, e: dict[str, Any]) -> list[dict[str, Any]]:
        if e["type"] == "substitution":
            player = e["player_in"]
        elif e["type"] in _KEY_TAG_TYPES:
            player = e.get("scorer") or e["player"]
        elif e["type"] in ("pass", "carry") and e["t"] - self._last_tag_t >= PLAYER_TAG_GAP_S \
                and e["player"] != self._last_tag_player:
            player = e["player"]
        else:
            return []
        info = self.state.roster[player]
        self._last_tag_t, self._last_tag_player = e["t"], player
        key = e["type"] in _KEY_TAG_TYPES or e["type"] == "substitution"
        stats = self.state.players[player]
        return [self._cue(e["t"], 4, "lower_third", "player_tag", {
            "team": info["team"], "player": player, "player_name": info["name"], "number": info["number"],
            "position": info["position"], "goals": stats.goals, "passes_completed": stats.passes_completed,
        }, 60 if key else 20, "all")]

    def _moment_cue(self, m: Moment) -> dict[str, Any]:
        if m.type == "danger_peak":
            return self._cue(m.t, 8, "banner", "danger", {
                "team": m.team, "danger": m.facts["danger"], "box_entries": m.facts["box_entries"],
                "shots": m.facts["shots"], "window_s": m.facts["window_s"], "main_channel": m.facts["main_channel"],
            }, 75, "all")
        return self._cue(m.t, 8, "banner", "moment", {
            "moment_id": m.moment_id, "type": m.type, "team": m.team, "minute": m.minute,
            "importance": m.importance, "headline": m.headline,
        }, m.importance, "analyst" if m.importance < 40 else "all")
