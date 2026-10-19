"""A replay session: one viewer watching a match "live" at a chosen speed.

Each browser session owns a replay (its own clock and speed), a MatchBrain and a
Watcher for the selected fan profile. Everything the viewer must see is pushed
to subscribers as typed messages, which the API turns into Server-Sent Events.
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from comeback.agents.brain import MatchBrain
from comeback.agents.llm import LLMGateway
from comeback.agents.watcher import Watcher
from comeback.engine.match import EngineUpdate, load_match
from comeback.fans.profiles import FanProfile
from comeback.fans.session import FanSession

log = logging.getLogger(__name__)

MATCHES_DIR = Path(__file__).resolve().parents[2] / "data" / "matches"
SPEEDS = (1, 5, 10, 20, 40)
MAX_SLEEP_S = 1.5  # dead-ball pauses are shortened so the replay never feels frozen
CARD_WAIT_S = 20.0  # how long a catch-up waits for pending verified cards before using templates


def cue_visible(cue: dict[str, Any], level: str) -> bool:
    """Whether an overlay cue is meant for a viewer of this level."""
    return cue["audience"] in ("all", level)


class ReplaySession:
    """Replays one match for one viewer and publishes everything that happens."""

    def __init__(self, session_id: str, match_id: str, profile: FanProfile, gateway: LLMGateway,
                 speed: int = 10) -> None:
        self.session_id = session_id
        self.match_id = match_id
        self.meta, self.events = load_match(MATCHES_DIR / f"{match_id}.jsonl")
        self.brain = MatchBrain(self.meta, gateway)
        self.speed = speed if speed in SPEEDS else 10
        self.index = 0
        self.paused = False
        self.away_bands: list[dict[str, float | None]] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._card_writer: asyncio.Task | None = None
        self._card_queue: asyncio.Queue = asyncio.Queue()
        self._wake = asyncio.Event()
        self.set_profile(profile)

    # -------------------------------------------------------- subscribers

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, kind: str, data: Any) -> None:
        for queue in self._subscribers:
            queue.put_nowait({"type": kind, "data": data})

    # ------------------------------------------------------------ control

    def set_profile(self, profile: FanProfile) -> None:
        self.fan = FanSession(profile, joined_at=self.brain.engine.state.t)
        self.watcher = Watcher(self.fan, self.brain.engine)

    def set_speed(self, speed: int) -> None:
        if speed in SPEEDS:
            self.speed = speed
            self._wake.set()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self._wake.set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            self._card_writer = asyncio.create_task(self._write_cards())

    async def stop(self) -> None:
        for task in (self._task, self._card_writer):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def state_message(self) -> dict[str, Any]:
        """Everything a (re)connecting client needs to draw the current state."""
        st = self.brain.engine.state
        return {
            "session": self.session_id, "match_id": self.match_id, "speed": self.speed, "paused": self.paused,
            "profile": self.fan.profile.__dict__, "present": self.fan.present,
            "away_bands": self.away_bands, "snapshot": self.brain.engine.snapshot(),
            "lineup": st.lineup,
            "timeline": self.brain.engine.timeline,
            "cards": sorted(self.brain.cards.values(), key=lambda c: c["t"]),
            "notifications": self.fan.notifications, "finished": st.finished,
        }

    # -------------------------------------------------------- fan actions

    def go_away(self) -> dict[str, Any]:
        t = self.brain.engine.state.t
        self.fan.go_away(t)
        self.away_bands.append({"from_t": t, "to_t": None})
        self.publish("presence", {"present": False, "t": t, "away_bands": self.away_bands})
        return {"present": False, "t": t}

    async def come_back(self) -> dict[str, Any] | None:
        t = self.brain.engine.state.t
        window = self.fan.come_back(t)
        if window is None:
            return None
        if self.away_bands and self.away_bands[-1]["to_t"] is None:
            self.away_bands[-1]["to_t"] = t
        self.publish("presence", {"present": True, "t": t, "away_bands": self.away_bands})
        await self._drain_cards()
        catchup = await self.brain.catchup(self.fan.profile, *window)
        catchup |= {"from_t": window[0], "to_t": window[1]}
        self.publish("catchup", catchup)
        return catchup

    async def join_at(self, minute: float) -> dict[str, Any]:
        """Late join: fast-forward silently to ``minute`` (second half if > 45), then tell the story so far."""
        target_period = 2 if minute >= 45 else 1
        while self.index < len(self.events):
            e = self.events[self.index]
            self._process(e, silent=True)
            self.index += 1
            if (e["period"], e["minute"] + e["second"] / 60) >= (target_period, minute):
                break
        t = self.brain.engine.state.t
        self.set_profile(self.fan.profile)
        self.fan.joined_at = t
        self.away_bands.append({"from_t": 0.0, "to_t": t, "late_join": True})
        await self._drain_cards()
        self.publish("state", self.state_message())
        catchup = await self.brain.catchup(self.fan.profile, 0.0, t, late_join=True)
        catchup |= {"from_t": 0.0, "to_t": t, "late_join": True}
        self.publish("catchup", catchup)
        self._wake.set()
        return catchup

    # ------------------------------------------------------------ the loop

    def _process(self, event: dict[str, Any], silent: bool = False) -> EngineUpdate:
        update = self.brain.process(event)
        for moment in update.moments:
            if self.brain.cards[moment.moment_id]["pending"]:
                self._card_queue.put_nowait(moment)
        if silent:
            return update
        level = self.fan.profile.level
        self.publish("event", event)
        for cue in update.cues:
            if cue_visible(cue, level):
                self.publish("cue", cue)
        for moment in update.moments:
            self.publish("card", self.brain.cards[moment.moment_id])
        timeline = self.brain.engine.timeline
        if timeline and timeline[-1]["t"] == event["t"]:
            self.publish("timeline", timeline[-1])
        for note in self.watcher.on_update(self.brain.engine, update):
            self.publish("notification", note.__dict__)
        self.publish("snapshot", self.brain.engine.snapshot())
        return update

    async def _run(self) -> None:
        try:
            while self.index < len(self.events):
                while self.paused:
                    self._wake.clear()
                    await self._wake.wait()
                event = self.events[self.index]
                self._process(event)
                self.index += 1
                if self.index < len(self.events):
                    gap = max(0.0, self.events[self.index]["t"] - event["t"])
                    self._wake.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._wake.wait(), timeout=min(gap / self.speed, MAX_SLEEP_S))
            self.publish("end", {"score": self.brain.engine.state.score_str()})
        except asyncio.CancelledError:
            raise
        except Exception:  # never let a bug kill the stream silently
            log.exception("replay %s crashed", self.session_id)
            self.publish("error", {"message": "replay stopped unexpectedly"})

    async def _write_cards(self) -> None:
        """Upgrade template cards to verified LLM cards, one at a time (rate-limited)."""
        while True:
            moment = await self._card_queue.get()
            try:
                card = await self.brain.write_card(moment)
                self.publish("card", card)
            except Exception:
                log.exception("card writing failed for %s", moment.moment_id)
            finally:
                self._card_queue.task_done()

    async def _drain_cards(self) -> None:
        """Let pending cards finish (bounded): a catch-up should tell verified stories."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._card_queue.join(), timeout=CARD_WAIT_S)
