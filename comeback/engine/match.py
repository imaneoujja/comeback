"""MatchEngine: feeds events one by one into state, danger, moments and overlays."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comeback.engine.danger import WEIGHTS, Contribution, DangerTracker, shot_weight
from comeback.engine.moments import Moment, MomentDetector
from comeback.engine.overlays import OverlayBuilder
from comeback.engine.pitch import PITCH_LENGTH, channel, in_box, in_final_third
from comeback.engine.state import MatchState

HIGH_REGAIN_REASONS = {"interception", "tackle"}


@dataclass
class EngineUpdate:
    """What one event produced."""

    event: dict[str, Any]
    moments: list[Moment] = field(default_factory=list)
    cues: list[dict[str, Any]] = field(default_factory=list)


class MatchEngine:
    """Pure-Python, incremental match intelligence (no LLM, no look-ahead)."""

    def __init__(self, meta: dict[str, Any]) -> None:
        self.meta = meta
        self.state = MatchState(meta)
        self.danger = {code: DangerTracker() for code in (self.state.home, self.state.away)}
        self.detector = MomentDetector(self.state, self.danger)
        self.overlays = OverlayBuilder(self.state)
        self.timeline: list[dict[str, Any]] = []
        self._timeline_key: tuple[int, int] | None = None

    @property
    def moments(self) -> list[Moment]:
        return self.detector.moments

    @property
    def cues(self) -> list[dict[str, Any]]:
        return self.overlays.cues

    def process(self, event: dict[str, Any]) -> EngineUpdate:
        """Ingest one event and return the moments and overlay cues it triggered."""
        danger_before = {code: tracker.value(event["t"]) for code, tracker in self.danger.items()}
        self.state.apply(event)
        self._feed_danger(event)
        moments = self.detector.detect(event, danger_before)
        cues = self.overlays.for_event(event, moments)
        self._update_timeline(event)
        return EngineUpdate(event, moments, cues)

    # ------------------------------------------------------------- danger

    def _feed_danger(self, e: dict[str, Any]) -> None:
        etype, team = e["type"], e.get("team")
        if etype == "goal":
            self.danger = {code: DangerTracker() for code in self.danger}
            self.detector.danger = self.danger
            return
        if etype in ("pass", "carry") and e.get("success", True):
            start = self.state.frame(team, e["x"], e["y"])
            end = self.state.frame(team, e["end_x"], e["end_y"])
            if in_box(*end) and not in_box(*start):
                self._add(team, e, "box_entry", WEIGHTS["box_entry"], channel(end[1]))
            elif etype == "pass" and in_final_third(end[0]):
                self._add(team, e, "final_third_pass", WEIGHTS["final_third_pass"])
        elif etype == "shot":
            self._add(team, e, "shot", shot_weight(e["xg"]))
        elif etype == "corner":
            self._add(team, e, "corner", WEIGHTS["corner"])
        elif etype == "possession_change" and e["reason"] in HIGH_REGAIN_REASONS:
            if self.state.frame(team, e["x"], e["y"])[0] > PITCH_LENGTH / 2:
                self._add(team, e, "ball_won_high", WEIGHTS["ball_won_high"])
        elif etype == "pressure" and e["success"]:
            self._add(team, e, "pressure_won", WEIGHTS["pressure_won"])

    def _add(self, team: str, e: dict[str, Any], kind: str, weight: float, chan: str | None = None) -> None:
        self.danger[team].add(Contribution(e["t"], kind, weight, chan, e["id"]))

    def danger_now(self, team: str) -> tuple[float, float]:
        """(danger index, slope over 30 s) of ``team`` at the current match time."""
        tracker, t = self.danger[team], self.state.t
        return tracker.value(t), tracker.slope(t)

    # ------------------------------------------------------------ views

    def snapshot(self) -> dict[str, Any]:
        """Compact, JSON-serialisable view of the current match state."""
        st = self.state
        control = st.control()
        share_5 = st.possession_share()
        share_all = st.possession_share(None)
        teams = {}
        for code in (st.home, st.away):
            danger, slope = self.danger_now(code)
            teams[code] = {
                "name": st.team_names[code],
                **st.teams[code].to_dict(),
                "possession": round(share_all[code], 3),
                "possession_5min": round(share_5[code], 3),
                "control": round(control[code], 3),
                "danger": round(danger, 1),
                "danger_slope": round(slope, 1),
                "players_on_pitch": st.players_on_pitch[code],
                "formation": st.formation[code],
            }
        return {
            "match_id": st.match_id, "t": st.t, "period": st.period, "minute": st.minute, "second": st.second,
            "home": st.home, "away": st.away, "score": dict(st.score), "score_str": st.score_str(),
            "possession": st.possession, "chaos_per_min": round(st.chaos_per_min(), 2),
            "teams": teams, "finished": st.finished,
        }

    def _update_timeline(self, e: dict[str, Any]) -> None:
        key = (e["period"], e["minute"])
        if key == self._timeline_key:
            return
        self._timeline_key = key
        st = self.state
        control = st.control()
        self.timeline.append({
            "t": e["t"], "period": e["period"], "minute": e["minute"], "score": st.score_str(),
            "danger": {code: round(self.danger_now(code)[0], 1) for code in self.danger},
            "control": {code: round(v, 3) for code, v in control.items()},
            "chaos_per_min": round(st.chaos_per_min(), 2),
        })


def load_match(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a match file: (``match_start`` metadata, events)."""
    with Path(path).open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return records[0], records[1:]


def run_engine(meta: dict[str, Any], events: list[dict[str, Any]]) -> MatchEngine:
    """Process a whole match and return the engine (for offline analysis and tests)."""
    engine = MatchEngine(meta)
    for event in events:
        engine.process(event)
    return engine
