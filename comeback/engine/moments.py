"""Key-moment detection with an importance score (0-100) and verifiable facts.

Each moment carries compact ``facts`` (computed numbers only) and the ids of the
events that prove them, so the Analyst agent never needs the raw event log and
the Verifier can check every number it writes.
"""

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from comeback.engine.danger import DangerTracker
from comeback.engine.state import MatchState

BIG_CHANCE_XG = 0.25
DANGER_PEAK = 70.0
DANGER_REARM = 45.0
CONTROL_MARGIN = 0.12
CONTROL_CHECK_S = 30.0
SWING_COOLDOWN_S = 300.0
SWING_START_S = 600.0


@dataclass
class Moment:
    """A key moment. Text fields are filled later by the agents."""

    moment_id: str
    t: float
    minute: int
    period: int
    type: str
    team: str | None
    players: list[str]
    importance: int
    facts: dict[str, Any]
    evidence_event_ids: list[str]
    headline: str | None = None
    why_it_matters: str | None = None
    verified: bool = False
    source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        del data["extra"]
        return data


class MomentDetector:
    """Detects key moments from the event stream, one event at a time."""

    def __init__(self, state: MatchState, danger: dict[str, DangerTracker]) -> None:
        self.state = state
        self.danger = danger
        self.moments: list[Moment] = []
        self._count = 0
        self._recent: deque[dict[str, Any]] = deque(maxlen=40)
        self._missed: dict[str, tuple[int, float]] = {}
        self._subbed_on: dict[str, int] = {}
        self._max_deficit = {state.home: 0, state.away: 0}
        self._peak_armed = {state.home: True, state.away: True}
        self._dominant: str | None = None
        self._last_swing_t = -SWING_COOLDOWN_S
        self._next_control_check = SWING_START_S
        self._fastest_shot = 0.0
        self._top_sprint = 0.0

    def detect(self, event: dict[str, Any], danger_before: dict[str, float]) -> list[Moment]:
        """Return the moments triggered by ``event`` (state already updated)."""
        self._recent.append(event)
        handler = getattr(self, f"_on_{event['type']}", None)
        found: list[Moment] = handler(event, danger_before) if handler else []
        found += self._danger_peaks(event)
        found += self._momentum_swing(event)
        self.moments += found
        return found

    # ----------------------------------------------------------- helpers

    def _new(self, e: dict[str, Any], mtype: str, team: str | None, players: list[str | None],
             importance: float, facts: dict[str, Any], evidence: list[str | None]) -> Moment:
        self._count += 1
        return Moment(
            moment_id=f"m{self._count:03d}",
            t=e["t"], minute=e["minute"], period=e["period"], type=mtype, team=team,
            players=[p for p in players if p], importance=int(round(min(100, importance))),
            facts=facts, evidence_event_ids=[i for i in evidence if i],
        )

    def _last(self, predicate) -> dict[str, Any] | None:
        return next((e for e in reversed(self._recent) if predicate(e)), None)

    def _name(self, player_id: str | None) -> str | None:
        return self.state.player_name(player_id)

    def _numbers(self) -> dict[str, Any]:
        """Players on the pitch per team, only when a red card made it uneven."""
        on_pitch = self.state.players_on_pitch
        return {"players_on_pitch": dict(on_pitch)} if len(set(on_pitch.values())) > 1 else {}

    # --------------------------------------------------------- per event

    def _on_goal(self, e: dict[str, Any], danger_before: dict[str, float]) -> list[Moment]:
        st, team = self.state, e["team"]
        opp = st.opponent(team)
        after = {st.home: e["score_home"], st.away: e["score_away"]}
        before = {**after, team: after[team] - 1}
        diff_before = before[team] - before[opp]
        diff_after = diff_before + 1
        if sum(before.values()) == 0:
            situation = "opener"
        elif diff_after == 0:
            situation = "equaliser"
        elif diff_before == 0:
            situation = "go_ahead"
        elif diff_after < 0:
            situation = "pulls_one_back"
        else:
            situation = "extends_lead"
        self._max_deficit[opp] = max(self._max_deficit[opp], after[team] - after[opp])

        scorer, assist = e["scorer"], e.get("assist")
        shot = self._last(lambda x: x["type"] == "shot" and x["player"] == scorer)
        assist_pass = self._last(lambda x: x["type"] == "pass" and x["player"] == assist
                                 and x.get("receiver") == scorer and x["success"]) if assist else None
        facts: dict[str, Any] = {
            "score_before": f"{before[st.home]}-{before[st.away]}",
            "score_after": f"{after[st.home]}-{after[st.away]}",
            "situation": situation,
            "scorer": scorer,
            "scorer_name": self._name(scorer),
            "assist": assist,
            "assist_name": self._name(assist),
            "xg": shot["xg"] if shot else None,
            "shot_speed_kmh": shot["shot_speed_kmh"] if shot else None,
            "body_part": shot["body_part"] if shot else None,
            f"danger_{team.lower()}_before": round(danger_before.get(team, 0.0)),
            "team_shots": st.teams[team].shots,
            "team_xg": round(st.teams[team].xg, 2),
            "scorer_goals_in_match": st.players[scorer].goals,
        }
        importance = 85 + 5 * (e["minute"] >= 80) + 5 * (situation in ("equaliser", "go_ahead"))
        if opp in st.red_card_t:
            facts["minutes_since_opponent_red_card"] = int((e["t"] - st.red_card_t[opp]) // 60)
        facts |= self._numbers()
        if scorer in self._missed:
            facts["missed_big_chance_minute"], facts["missed_big_chance_xg"] = self._missed[scorer]
            importance += 3
        if scorer in self._subbed_on:
            facts["came_on_minute"] = self._subbed_on[scorer]
            importance += 3
        if self._max_deficit[team] >= 2 and diff_after >= 0:
            facts["comeback_from_deficit"] = self._max_deficit[team]
            importance += 3
        evidence = [assist_pass["id"] if assist_pass else None, shot["id"] if shot else None, e["id"]]
        return [self._new(e, "goal", team, [scorer, assist], importance, facts, evidence)]

    def _on_shot(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        found = []
        speed = e["shot_speed_kmh"]
        if speed > self._fastest_shot and e["minute"] >= 15 and speed >= 100:
            found.append(self._new(e, "milestone", e["team"], [e["player"]], 30, {
                "milestone": "fastest_shot_so_far", "player": e["player"], "player_name": self._name(e["player"]),
                "shot_speed_kmh": speed, "previous_fastest_kmh": self._fastest_shot,
            }, [e["id"]]))
        self._fastest_shot = max(self._fastest_shot, speed)
        if e["xg"] >= BIG_CHANCE_XG and e["outcome"] != "goal":
            self._missed[e["player"]] = (e["minute"], e["xg"])
            found.append(self._new(e, "big_chance", e["team"], [e["player"]], 55 + 50 * e["xg"], {
                "player": e["player"], "player_name": self._name(e["player"]), "xg": e["xg"],
                "outcome": e["outcome"], "shot_speed_kmh": speed, "body_part": e["body_part"],
                "score": self.state.score_str(), **self._numbers(),
            }, [e["id"]]))
        return found

    def _on_card(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        if e["color"] != "red":
            return []
        return [self._new(e, "red_card", e["team"], [e["player"]], 85, {
            "player": e["player"], "player_name": self._name(e["player"]),
            "reason": e.get("reason"), "second_yellow": bool(e.get("second_yellow")),
            "players_left": self.state.players_on_pitch[e["team"]], "score": self.state.score_str(),
        }, [e["id"]])]

    def _on_foul(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        if not e.get("penalty"):
            return []
        awarded_to = self.state.opponent(e["team"])
        return [self._new(e, "penalty", awarded_to, [e["opponent"], e["player"]], 75, {
            "fouled_player": e["opponent"], "fouled_player_name": self._name(e["opponent"]),
            "offender": e["player"], "offender_name": self._name(e["player"]), "score": self.state.score_str(),
        }, [e["id"]])]

    def _on_substitution(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        self._subbed_on[e["player_in"]] = e["minute"]
        facts = {
            "player_in": e["player_in"], "player_in_name": self._name(e["player_in"]),
            "player_out": e["player_out"], "player_out_name": self._name(e["player_out"]),
            "score": self.state.score_str(),
        }
        if e.get("formation"):
            facts["formation"] = e["formation"]
            return [self._new(e, "shape_change", e["team"], [e["player_in"], e["player_out"]], 60, facts, [e["id"]])]
        return [self._new(e, "substitution", e["team"], [e["player_in"], e["player_out"]], 20, facts, [e["id"]])]

    def _on_pass(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        stats = self.state.players[e["player"]]
        if not (e["success"] and stats.passes_completed == 50):
            return []
        return [self._new(e, "milestone", e["team"], [e["player"]], 25, {
            "milestone": "50_completed_passes", "player": e["player"], "player_name": self._name(e["player"]),
            "completed_passes": 50, "pass_accuracy": round(stats.passes_completed / stats.passes, 3),
        }, [e["id"]])]

    def _on_sprint(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        speed = e["speed_kmh"]
        record = speed > self._top_sprint and e["minute"] >= 10 and speed >= 34
        previous, self._top_sprint = self._top_sprint, max(self._top_sprint, speed)
        if not record:
            return []
        return [self._new(e, "milestone", e["team"], [e["player"]], 25, {
            "milestone": "top_speed_so_far", "player": e["player"], "player_name": self._name(e["player"]),
            "speed_kmh": speed, "previous_top_kmh": previous,
        }, [e["id"]])]

    def _on_period_end(self, e: dict[str, Any], _: dict[str, float]) -> list[Moment]:
        st = self.state
        possession = st.possession_share(None)
        facts: dict[str, Any] = {"score": st.score_str()}
        for code in (st.home, st.away):
            ts = st.teams[code]
            facts[code] = {
                "shots": ts.shots, "xg": round(ts.xg, 2), "possession": round(possession[code], 2),
                "pass_accuracy": round(ts.passes_completed / ts.passes, 2) if ts.passes else None,
                "corners": ts.corners,
            }
        mtype, importance = ("half_time", 50) if e["period"] == 1 else ("full_time", 70)
        return [self._new(e, mtype, None, [], importance, facts, [e["id"]])]

    # ------------------------------------------------------ continuous

    def _danger_peaks(self, e: dict[str, Any]) -> list[Moment]:
        found = []
        for team, tracker in self.danger.items():
            value = tracker.value(e["t"])
            if value < DANGER_REARM:
                self._peak_armed[team] = True
            elif value >= DANGER_PEAK and self._peak_armed[team]:
                self._peak_armed[team] = False
                reasons = tracker.reasons(e["t"])
                facts = {"danger": round(value), "score": self.state.score_str(),
                         **{k: v for k, v in reasons.items() if k != "evidence_event_ids"}}
                found.append(self._new(e, "danger_peak", team, [], 50 + (value - DANGER_PEAK) / 2,
                                       facts, list(reasons["evidence_event_ids"])))
        return found

    def _momentum_swing(self, e: dict[str, Any]) -> list[Moment]:
        if e["t"] < self._next_control_check:
            return []
        self._next_control_check = e["t"] + CONTROL_CHECK_S
        st = self.state
        control = st.control()
        diff = control[st.home] - control[st.away]
        dominant = st.home if diff > CONTROL_MARGIN else st.away if diff < -CONTROL_MARGIN else None
        if dominant is None or dominant == self._dominant:
            return []
        if self._dominant is not None and e["t"] - self._last_swing_t < SWING_COOLDOWN_S:
            return []
        previous, self._dominant = self._dominant, dominant
        if previous is None:
            return []
        self._last_swing_t = e["t"]
        share = st.possession_share()
        facts = {
            "now_in_control": dominant, "previously_in_control": previous,
            "possession_last_5min": {k: round(v, 2) for k, v in share.items()},
            "pass_accuracy_last_5min": {k: round(st.rolling_pass_accuracy(k), 2) for k in control},
            "score": st.score_str(), **self._numbers(),
        }
        return [self._new(e, "momentum_swing", dominant, [], 55, facts, [e["id"]])]
