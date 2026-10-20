"""MatchBrain: the shared state every agent reads (one per match, whatever the number of fans).

* the MatchEngine (state, danger, moments, overlay cues),
* the Moment Store: one card per moment, written once by Analyst → Verifier and
  shared by all fans. A template card is stored immediately so nobody waits for
  the LLM; it is upgraded when the verified LLM card arrives.
"""

from typing import Any

from comeback.agents.analyst import AnalystTask, needs_analyst, write_moment_card
from comeback.agents.llm import LLMGateway
from comeback.agents.storyteller import CatchupTask, write_catchup
from comeback.agents.templates import moment_card_text
from comeback.agents.workflow import Tracer
from comeback.engine.match import EngineUpdate, MatchEngine
from comeback.engine.moments import Moment
from comeback.fans.catchup import build_delta, length_bucket, select_cards
from comeback.fans.profiles import FanProfile


class MatchBrain:
    """Engine + Moment Store + access to the writing agents."""

    def __init__(self, meta: dict[str, Any], gateway: LLMGateway) -> None:
        self.engine = MatchEngine(meta)
        self.gateway = gateway
        self.cards: dict[str, dict[str, Any]] = {}
        self._situations: dict[str, dict[str, Any]] = {}
        st = self.engine.state
        self.team_names = dict(st.team_names)
        self.roster = st.roster

    def process(self, event: dict[str, Any]) -> EngineUpdate:
        """Feed one event; store provisional template cards for new moments."""
        update = self.engine.process(event)
        for moment in update.moments:
            self._situations[moment.moment_id] = self._situation()  # as it was when the moment happened
            data = moment.to_dict()
            self.cards[moment.moment_id] = {
                **data, **moment_card_text(data, self.team_names), "verified": True, "source": "template",
                "pending": needs_analyst(data),
            }
        return update

    def _recent_headlines(self, before_t: float) -> list[str]:
        return [f"{c['minute']}' {c['headline']}" for c in self.cards.values()
                if c["t"] < before_t and c["importance"] >= 50 and c["type"] != "danger_peak"]

    def _situation(self) -> dict[str, Any]:
        st = self.engine.state
        return {"score": f"{self.team_names[st.home]} {st.score_str()} {self.team_names[st.away]}",
                "players_on_pitch": {self.team_names[c]: n for c, n in st.players_on_pitch.items()}}

    async def write_card(self, moment: Moment, trace: Tracer | None = None) -> dict[str, Any]:
        """Run Analyst → Verifier for one moment and upgrade the stored card."""
        data = moment.to_dict()
        situation = self._situations.get(moment.moment_id) or self._situation()
        task = AnalystTask(data, self.team_names, self.roster, self._recent_headlines(moment.t), situation)
        card = {**await write_moment_card(task, self.gateway, trace), "pending": False}
        self.cards[moment.moment_id] = card
        return card

    async def catchup(self, profile: FanProfile, from_t: float, to_t: float,
                      late_join: bool = False, trace: Tracer | None = None, final: bool = False,
                      snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        """Personalised catch-up for the window ``[from_t, to_t]``.

        ``snapshot`` is the match as it was at ``to_t`` (the moment the fan came back): the live
        match keeps moving while pending cards are drained, and the story must not drift with it.
        """
        cards = sorted(self.cards.values(), key=lambda c: c["t"])
        in_window = [c for c in cards if from_t <= c["t"] <= to_t]
        bucket = length_bucket(to_t - from_t, late_join or final)
        selected = select_cards(cards, from_t, to_t, profile, bucket)
        now = snapshot or self.engine.snapshot()
        delta = build_delta(self.engine.timeline, now, from_t, self.team_names, in_window)
        task = CatchupTask(profile, bucket, selected, delta, self.team_names, self.roster, late_join, final)
        return await write_catchup(task, self.gateway, trace)

    async def final_recap(self, profile: FanProfile, trace: Tracer | None = None) -> dict[str, Any]:
        """Full-time recap of the whole match for one fan ("Gazette"), plus the key moments it draws on."""
        recap = await self.catchup(profile, 0.0, self.engine.state.t, trace=trace, final=True)
        cards = sorted(self.cards.values(), key=lambda c: c["t"])
        key = sorted((c for c in cards if c["type"] not in ("danger_peak", "full_time", "half_time")),
                     key=lambda c: c["importance"], reverse=True)[:6]
        key.sort(key=lambda c: c["t"])
        recap["key_moments"] = [{"minute": c["minute"], "type": c["type"], "team": c["team"],
                                 "headline": c["headline"]} for c in key]
        return recap
