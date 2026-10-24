"""Incremental match state: score, clock, possession and team/player statistics."""

import math
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from comeback.engine.pitch import attacking_frame, in_box, in_final_third

ROLLING_WINDOW_S = 300.0
KEY_PASS_WINDOW_S = 15.0   # a shot this soon after a completed pass to the shooter makes it a key pass
ON_BALL_TYPES = {"pass", "carry", "sprint", "shot", "throw_in", "goal_kick", "corner"}


@dataclass
class PlayerStats:
    """Running statistics of one player."""

    player_id: str
    passes: int = 0
    passes_completed: int = 0
    difficulty_sum: float = 0.0
    progressive_passes: int = 0
    shots: int = 0
    xg: float = 0.0
    goals: int = 0
    assists: int = 0
    big_chances_missed: int = 0
    top_speed_kmh: float = 0.0
    sprints: int = 0
    distance_with_ball_m: float = 0.0
    tackles_won: int = 0
    interceptions: int = 0
    key_passes: int = 0      # completed passes the receiver shot from
    duels: int = 0           # tackles, as the tackler or the player tackled
    duels_won: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["xg"] = round(self.xg, 2)
        data["distance_with_ball_m"] = round(self.distance_with_ball_m)
        data["pass_accuracy"] = round(self.passes_completed / self.passes, 3) if self.passes else None
        data["avg_pass_difficulty"] = round(self.difficulty_sum / self.passes, 1) if self.passes else None
        del data["difficulty_sum"]
        return data


@dataclass
class TeamStats:
    """Running statistics of one team."""

    team: str
    passes: int = 0
    passes_completed: int = 0
    difficulty_sum: float = 0.0
    progressive_passes: int = 0
    final_third_passes: int = 0
    box_entries: int = 0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    goals: int = 0
    corners: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    turnovers: int = 0
    possession_s: float = 0.0
    fastest_shot_kmh: float = 0.0
    top_sprint_kmh: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["xg"] = round(self.xg, 2)
        data["possession_s"] = round(self.possession_s)
        data["pass_accuracy"] = round(self.passes_completed / self.passes, 3) if self.passes else None
        data["avg_pass_difficulty"] = round(self.difficulty_sum / self.passes, 1) if self.passes else None
        del data["difficulty_sum"]
        return data


class MatchState:
    """Match state updated one event at a time (true streaming, no look-ahead)."""

    def __init__(self, meta: dict[str, Any]) -> None:
        self.match_id: str = meta["match_id"]
        self.home: str = meta["home"]["id"]
        self.away: str = meta["away"]["id"]
        self.team_names = {meta[s]["id"]: meta[s]["name"] for s in ("home", "away")}
        self.roster: dict[str, dict[str, Any]] = {
            p["id"]: {**p, "team": meta[s]["id"]} for s in ("home", "away") for p in meta[s]["players"]
        }
        self.formation = {self.home: meta["home"].get("formation"), self.away: meta["away"].get("formation")}
        self.players_on_pitch = {self.home: 11, self.away: 11}
        # Who is on the pitch and at which base spot (team attacking frame), for renderers.
        self.lineup: dict[str, dict[str, list[float]]] = {
            meta[s]["id"]: {p["id"]: p["spot"] for p in meta[s]["players"] if p.get("spot")}
            for s in ("home", "away")
        }
        self.teams = {code: TeamStats(code) for code in (self.home, self.away)}
        self.players = {pid: PlayerStats(pid) for pid in self.roster}
        self.score = {self.home: 0, self.away: 0}
        self.t = 0.0
        self.minute = 0
        self.second = 0
        self.period = 1
        self.possession: str | None = None
        self.finished = False
        self.red_card_t: dict[str, float] = {}
        self.last_shot_t: dict[str, float] = {}
        self._possession_log: deque[tuple[float, float, str]] = deque()
        self._pass_log: deque[tuple[float, str, bool]] = deque()
        self._chaos_log: deque[float] = deque()
        self._last_pass: tuple[str, str, str, float] | None = None   # (team, passer, receiver, t)

    # ----------------------------------------------------------- helpers

    def opponent(self, team: str) -> str:
        return self.away if team == self.home else self.home

    def is_home(self, team: str) -> bool:
        return team == self.home

    def frame(self, team: str, x: float, y: float) -> tuple[float, float]:
        """Absolute point → attacking frame of ``team``."""
        return attacking_frame(x, y, self.is_home(team))

    def seconds_since_shot(self, team: str) -> float:
        """Seconds since ``team``'s last shot (infinite if none yet)."""
        return self.t - self.last_shot_t[team] if team in self.last_shot_t else float("inf")

    def score_str(self) -> str:
        return f"{self.score[self.home]}-{self.score[self.away]}"

    def player_name(self, player_id: str | None) -> str | None:
        return self.roster[player_id]["name"] if player_id in self.roster else None

    # ---------------------------------------------------------- updating

    def apply(self, event: dict[str, Any]) -> None:
        """Update the state with one event."""
        self._advance_clock(event)
        handler = getattr(self, f"_on_{event['type']}", None)
        if handler:
            handler(event)
        if event["type"] in ON_BALL_TYPES and event.get("team"):
            self.possession = event["team"]

    def _advance_clock(self, event: dict[str, Any]) -> None:
        dt = max(0.0, event["t"] - self.t)
        if self.possession and dt:
            self.teams[self.possession].possession_s += dt
            self._possession_log.append((self.t, event["t"], self.possession))
        self.t, self.minute, self.second, self.period = event["t"], event["minute"], event["second"], event["period"]
        cutoff = self.t - ROLLING_WINDOW_S
        while self._possession_log and self._possession_log[0][1] < cutoff:
            self._possession_log.popleft()
        while self._pass_log and self._pass_log[0][0] < cutoff:
            self._pass_log.popleft()
        while self._chaos_log and self._chaos_log[0] < cutoff:
            self._chaos_log.popleft()

    def _on_pass(self, e: dict[str, Any]) -> None:
        team, player = self.teams[e["team"]], self.players[e["player"]]
        for s in (team, player):
            s.passes += 1
            s.passes_completed += e["success"]
            s.difficulty_sum += e["difficulty"]
            s.progressive_passes += e["success"] and e["progressive"]
        self._pass_log.append((e["t"], e["team"], e["success"]))
        self._last_pass = (e["team"], e["player"], e["receiver"], e["t"]) if e["success"] else None
        if e["success"]:
            start = self.frame(e["team"], e["x"], e["y"])
            end = self.frame(e["team"], e["end_x"], e["end_y"])
            team.final_third_passes += in_final_third(end[0])
            team.box_entries += in_box(*end) and not in_box(*start)

    def _on_carry(self, e: dict[str, Any]) -> None:
        start = self.frame(e["team"], e["x"], e["y"])
        end = self.frame(e["team"], e["end_x"], e["end_y"])
        self.teams[e["team"]].box_entries += in_box(*end) and not in_box(*start)
        self.players[e["player"]].distance_with_ball_m += math.dist(start, end)

    def _on_sprint(self, e: dict[str, Any]) -> None:
        player, team = self.players[e["player"]], self.teams[e["team"]]
        player.sprints += 1
        player.top_speed_kmh = max(player.top_speed_kmh, e["speed_kmh"])
        team.top_sprint_kmh = max(team.top_sprint_kmh, e["speed_kmh"])

    def _on_shot(self, e: dict[str, Any]) -> None:
        team, player = self.teams[e["team"]], self.players[e["player"]]
        for s in (team, player):
            s.shots += 1
            s.xg += e["xg"]
        team.shots_on_target += e["outcome"] in ("goal", "saved")
        team.fastest_shot_kmh = max(team.fastest_shot_kmh, e["shot_speed_kmh"])
        self.last_shot_t[e["team"]] = e["t"]
        last = self._last_pass
        if last and last[0] == e["team"] and last[2] == e["player"] and e["t"] - last[3] <= KEY_PASS_WINDOW_S:
            self.players[last[1]].key_passes += 1
        self._last_pass = None
        if e["xg"] >= 0.25 and e["outcome"] != "goal":
            player.big_chances_missed += 1

    def _on_goal(self, e: dict[str, Any]) -> None:
        self.score = {self.home: e["score_home"], self.away: e["score_away"]}
        self.teams[e["team"]].goals += 1
        self.players[e["scorer"]].goals += 1
        if e.get("assist"):
            self.players[e["assist"]].assists += 1
        self.possession = None

    def _on_possession_change(self, e: dict[str, Any]) -> None:
        self._last_pass = None
        self.teams[e["from_team"]].turnovers += 1
        self.possession = e["to_team"]
        self._chaos_log.append(e["t"])

    def _on_tackle(self, e: dict[str, Any]) -> None:
        tackler = self.players[e["player"]]
        tackler.tackles_won += e["won"]
        tackler.duels += 1
        tackler.duels_won += e["won"]
        if e.get("opponent") in self.players:
            self.players[e["opponent"]].duels += 1
            self.players[e["opponent"]].duels_won += not e["won"]
        self._chaos_log.append(e["t"])

    def _on_interception(self, e: dict[str, Any]) -> None:
        self.players[e["player"]].interceptions += 1

    def _on_pressure(self, e: dict[str, Any]) -> None:
        if e["success"]:
            self._chaos_log.append(e["t"])

    def _on_foul(self, e: dict[str, Any]) -> None:
        self.teams[e["team"]].fouls += 1
        self._chaos_log.append(e["t"])

    def _on_corner(self, e: dict[str, Any]) -> None:
        self.teams[e["team"]].corners += 1

    def _on_card(self, e: dict[str, Any]) -> None:
        team = self.teams[e["team"]]
        if e["color"] == "red":
            team.red_cards += 1
            self.lineup[e["team"]].pop(e["player"], None)
            self.players_on_pitch[e["team"]] -= 1
            self.red_card_t[e["team"]] = e["t"]
        else:
            team.yellow_cards += 1

    def _on_substitution(self, e: dict[str, Any]) -> None:
        lineup = self.lineup[e["team"]]
        spot = e.get("spot") or lineup.get(e["player_out"])
        lineup.pop(e["player_out"], None)
        if spot:
            lineup[e["player_in"]] = spot
        if e.get("formation"):
            self.formation[e["team"]] = e["formation"]

    def _on_match_end(self, e: dict[str, Any]) -> None:
        self.finished = True

    # ------------------------------------------------------ rolling views

    def possession_share(self, window_s: float | None = ROLLING_WINDOW_S) -> dict[str, float]:
        """Share of possession time per team, overall (``None``) or over a rolling window."""
        if window_s is None:
            totals = {code: s.possession_s for code, s in self.teams.items()}
        else:
            cutoff = self.t - window_s
            totals = {self.home: 0.0, self.away: 0.0}
            for start, end, team in self._possession_log:
                totals[team] += max(0.0, end - max(start, cutoff))
        total = sum(totals.values())
        return {code: (v / total if total else 0.5) for code, v in totals.items()}

    def rolling_pass_accuracy(self, team: str) -> float:
        """Pass accuracy over the rolling window (0.8 when there is no data yet)."""
        results = [ok for _, code, ok in self._pass_log if code == team]
        return sum(results) / len(results) if results else 0.8

    def control(self) -> dict[str, float]:
        """Control per team = rolling possession share x rolling pass accuracy (0-1)."""
        share = self.possession_share()
        return {code: share[code] * self.rolling_pass_accuracy(code) for code in (self.home, self.away)}

    def chaos_per_min(self) -> float:
        """Turnovers + duels per minute over the rolling window."""
        window_min = min(ROLLING_WINDOW_S, max(self.t, 60.0)) / 60
        return len(self._chaos_log) / window_min
