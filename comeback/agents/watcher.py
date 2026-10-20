"""Watcher agent: one per fan, watches the match while the fan is away.

It reads the shared match brain (engine state + danger index) and decides, with
deterministic rules, when to call the fan back *before* the big moment, and why.
It also sends an after-the-fact goal notification, and a "called it" receipt when a
goal follows one of its call-backs and the fan is back in time. No LLM call: decisions
must be instant and cost-free per fan, which is what lets the design scale to every viewer.
"""

from dataclasses import dataclass, field
from typing import Any

from comeback.agents.templates import (
    ALERT_TEXT,
    CALLED_IT_TEXT,
    GOAL_ALERT_TEXT,
    SIDE_TEXT,
    SIDE_WORDS,
    pressure_texts,
)
from comeback.engine.alerts import AlertRule, AlertTracker
from comeback.engine.match import EngineUpdate, MatchEngine
from comeback.fans.session import FanSession

MAX_ALERTS_PER_ABSENCE = 2
CALLED_IT_WINDOW_S = 300.0  # a call-back "called" a goal scored by the same team within 5 minutes
_DEFENDING_SIDE = {"left": "right", "right": "left"}  # attacking left channel = defenders' right side


@dataclass
class Notification:
    """A message pushed to the fan's phone."""

    kind: str  # "come_back" | "goal" | "called_it"
    t: float
    minute: int
    team: str
    text: str
    facts: dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: list[str] = field(default_factory=list)


class Watcher:
    """Per-fan agent: alert decisions from the shared danger index, phrased in the fan's language."""

    def __init__(self, session: FanSession, engine: MatchEngine, rule: AlertRule | None = None) -> None:
        self.session = session
        self.state = engine.state
        st = engine.state
        self.teams = session.profile.relevant_teams(st.home, st.away)
        self.trackers = {team: AlertTracker(rule) for team in self.teams}

    def on_update(self, engine: MatchEngine, update: EngineUpdate) -> list[Notification]:
        """React to one processed event; returns notifications for this fan."""
        e, out = update.event, []
        if self.session.present:
            receipt = self._called_it(e) if e["type"] == "goal" else None
            if receipt:
                self.session.notifications.append(receipt.__dict__)
            return [receipt] if receipt else []
        if e["type"] == "goal":
            out.append(self._goal(e))
        elif self.session.alerts_this_absence < MAX_ALERTS_PER_ABSENCE:
            for team in self.teams:
                danger, slope = engine.danger_now(team)
                if self.trackers[team].check(e["t"], danger, slope, engine.state.seconds_since_shot(team)):
                    out.append(self._come_back(engine, team, e, danger))
                    self.session.alerts_this_absence += 1
                    break
        self.session.notifications += [n.__dict__ for n in out]
        return out

    def _come_back(self, engine: MatchEngine, team: str, e: dict[str, Any], danger: float) -> Notification:
        st, lang = self.state, self.session.profile.language
        reasons = engine.danger[team].reasons(e["t"])
        club = self.session.profile.pov_team()
        attacking_view = club is None or club == team
        names = st.team_names
        if attacking_view:
            side = _DEFENDING_SIDE.get(reasons["main_channel"] or "")
            side_text = SIDE_TEXT[lang].format(opponent=names[st.opponent(team)], side=SIDE_WORDS[side][lang]) \
                if side else ""
            text = ALERT_TEXT["attacking"][lang].format(
                team=names[team], side_text=side_text, **pressure_texts(lang, reasons["box_entries"], reasons["shots"]))
        else:
            pressure = pressure_texts(lang, reasons["box_entries"], reasons["shots"])
            text = ALERT_TEXT["defending"][lang].format(team=names[club], opponent=names[team], **pressure)
        facts = {"danger": round(danger), "score": st.score_str(),
                 **{k: v for k, v in reasons.items() if k != "evidence_event_ids"},
                 "decision": self._decision(engine, team, e, club)}
        return Notification("come_back", e["t"], e["minute"], team, text, facts, list(reasons["evidence_event_ids"]))

    def _decision(self, engine: MatchEngine, team: str, e: dict[str, Any], club: str | None) -> dict[str, Any]:
        """Why this fan, why now: every condition the rule checked, for the visible decision chain."""
        rule = self.trackers[team].rule
        _, slope = engine.danger_now(team)
        away_since = self.session.away_since
        return {
            "threshold": rule.threshold, "slope": round(slope, 1), "min_slope": rule.min_slope,
            "since_own_shot_s": round(min(engine.state.seconds_since_shot(team), 9999)),
            "quiet_after_shot_s": rule.quiet_after_shot_s, "cooldown_s": rule.cooldown_s,
            "away_for_s": round(e["t"] - away_since) if away_since is not None else None,
            "relation": "attacking" if club == team else "defending" if club else "neutral",
            "fan_team": club, "alert_number": self.session.alerts_this_absence + 1,
            "max_alerts": MAX_ALERTS_PER_ABSENCE,
        }

    def phrase_for(self, engine: MatchEngine, team: str, e: dict[str, Any], danger: float) -> str:
        """The call-back text this fan would get for the same moment (used to show personalisation side by side)."""
        return self._come_back(engine, team, e, danger).text

    def _called_it(self, e: dict[str, Any]) -> Notification | None:
        """A goal right after a call-back for the scoring team, with the fan back: the alert was right."""
        alerts = [n for n in self.session.notifications if n["kind"] == "come_back" and n["team"] == e["team"]
                  and 0 < e["t"] - n["t"] <= CALLED_IT_WINDOW_S]
        if not alerts:
            return None
        alert = alerts[-1]
        lang = self.session.profile.language
        text = CALLED_IT_TEXT[lang].format(alert_minute=alert["minute"], minute=e["minute"])
        facts = {"alert_minute": alert["minute"], "goal_minute": e["minute"], "lead_s": round(e["t"] - alert["t"]),
                 "score": self.state.score_str()}
        return Notification("called_it", e["t"], e["minute"], e["team"], text, facts, [e["id"]])

    def _goal(self, e: dict[str, Any]) -> Notification:
        st, lang = self.state, self.session.profile.language
        text = GOAL_ALERT_TEXT[lang].format(
            scorer_name=st.player_name(e["scorer"]), minute=e["minute"], home=st.team_names[st.home],
            away=st.team_names[st.away], score=st.score_str())
        return Notification("goal", e["t"], e["minute"], e["team"], text,
                            {"score": st.score_str(), "scorer": e["scorer"]}, [e["id"]])
