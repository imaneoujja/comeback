"""A simulated audience of thousands of fans served by one shared match brain.

Each simulated fan has a club (or none), a level and a language, leaves and
returns at random, may join late, receives come-back alerts and goal
notifications, and gets a catch-up when they return. The point is to *measure*
the scale argument: alert decisions are computed once per team, and a catch-up
only needs a new LLM story when its (moments, language, level, club, length)
key has never been written before.
"""

import random
from typing import Any

from comeback.engine.alerts import AlertTracker
from comeback.engine.match import EngineUpdate, MatchEngine
from comeback.fans.catchup import length_bucket, select_cards
from comeback.fans.profiles import FanProfile

PRESENT, AWAY, CALLED, NOT_JOINED = 0, 1, 2, 3
TICK_S = 15.0
MEAN_PRESENCE_S = 25 * 60
MEAN_ABSENCE_S = 6 * 60
LATE_JOIN_SHARE = 0.15
RETURN_ON_ALERT = 0.65
MAX_ALERTS_PER_ABSENCE = 2
BACK_IN_TIME_WINDOW_S = 6 * 60
LANGUAGES = ("en", "en", "es", "fr")


class Crowd:
    """Thousands of viewers with random absences; tracks what serving them costs."""

    def __init__(self, engine: MatchEngine, size: int = 10_000, seed: int = 11) -> None:
        self.size = size
        self.rng = random.Random(seed)
        st = engine.state
        self.home, self.away = st.home, st.away
        rng = self.rng
        self.club: list[str | None] = [
            st.home if r < 0.45 else st.away if r < 0.8 else None for r in (rng.random() for _ in range(size))
        ]
        self.profiles: list[FanProfile] = [
            FanProfile(f"crowd-{i}", "fan", club, None, "analyst" if rng.random() < 0.3 else "casual",
                       rng.choice(LANGUAGES))
            for i, club in enumerate(self.club)
        ]
        self.state = bytearray(size)
        self.next_t = [0.0] * size
        self.away_since = [0.0] * size
        self.alerts = [0] * size
        self.called_at = [-1e9] * size
        for i in range(size):
            if rng.random() < LATE_JOIN_SHARE:
                self.state[i] = NOT_JOINED
                self.next_t[i] = rng.uniform(10 * 60, 75 * 60)
            else:
                self.next_t[i] = rng.expovariate(1 / MEAN_PRESENCE_S)
        self.trackers = {team: AlertTracker() for team in (st.home, st.away)}
        self._next_tick = 0.0
        self.alerts_sent = 0
        self.goal_notifications = 0
        self.catchups = 0
        self.story_keys: set[tuple] = set()
        self.back_in_time: list[dict[str, Any]] = []
        self.ticked = False

    # ---------------------------------------------------------------- events

    def on_event(self, engine: MatchEngine, update: EngineUpdate, cards: dict[str, dict[str, Any]]) -> None:
        """Advance the crowd with one processed event of the shared engine."""
        st = engine.state
        t = st.t
        self.ticked = False
        for team, tracker in self.trackers.items():   # one decision per team, whatever the audience size
            danger, slope = engine.danger_now(team)
            if tracker.check(t, danger, slope, st.seconds_since_shot(team)):
                self._call_back(t)
        if update.event["type"] == "goal":
            self._goal(update.event, t)
        if t >= self._next_tick:
            self._tick(t, list(cards.values()))
            self._next_tick = t + TICK_S
            self.ticked = True

    def _call_back(self, t: float) -> None:
        rng = self.rng
        for i in range(self.size):
            if self.state[i] in (AWAY, CALLED) and self.alerts[i] < MAX_ALERTS_PER_ABSENCE:
                self.alerts[i] += 1
                self.alerts_sent += 1
                self.state[i] = CALLED
                self.called_at[i] = t
                if rng.random() < RETURN_ON_ALERT:
                    self.next_t[i] = min(self.next_t[i], t + rng.uniform(20, 120))

    def _goal(self, event: dict[str, Any], t: float) -> None:
        self.goal_notifications += sum(1 for s in self.state if s in (AWAY, CALLED))
        back = sum(1 for i in range(self.size)
                   if self.state[i] == PRESENT and t - self.called_at[i] <= BACK_IN_TIME_WINDOW_S)
        self.back_in_time.append({"minute": event["minute"], "team": event["team"], "fans": back})

    def _tick(self, t: float, cards: list[dict[str, Any]]) -> None:
        rng = self.rng
        for i in range(self.size):
            if t < self.next_t[i]:
                continue
            state = self.state[i]
            if state == PRESENT:
                self.state[i], self.away_since[i], self.alerts[i] = AWAY, t, 0
                self.next_t[i] = t + rng.expovariate(1 / MEAN_ABSENCE_S)
            else:
                late = state == NOT_JOINED
                start = 0.0 if late else self.away_since[i]
                self._catchup(i, start, t, late, cards)
                self.state[i] = PRESENT
                self.next_t[i] = t + rng.expovariate(1 / MEAN_PRESENCE_S)

    def _catchup(self, i: int, from_t: float, to_t: float, late: bool, cards: list[dict[str, Any]]) -> None:
        profile = self.profiles[i]
        bucket = length_bucket(to_t - from_t, late)
        selected = select_cards(cards, from_t, to_t, profile, bucket)
        self.catchups += 1
        self.story_keys.add((tuple(c["moment_id"] for c in selected), profile.language, profile.level,
                             profile.club_id, bucket, late))

    # ---------------------------------------------------------------- view

    def cost(self, analyst_calls: int) -> dict[str, int]:
        """What serving this crowd cost, versus one LLM call per catch-up."""
        return {"fans": self.size, "catchups": self.catchups, "stories": len(self.story_keys),
                "llm_calls": analyst_calls + len(self.story_keys), "naive_llm_calls": analyst_calls + self.catchups}

    def snapshot(self, analyst_calls: int) -> dict[str, Any]:
        """Counters and a compact per-fan state string ('0' watching, '1' away, '2' called back, '3' not joined)."""
        counts = [0, 0, 0, 0]
        for s in self.state:
            counts[s] += 1
        stories = len(self.story_keys)
        llm_calls = analyst_calls + stories
        return {
            "size": self.size, "watching": counts[PRESENT], "away": counts[AWAY] + counts[CALLED],
            "called": counts[CALLED], "not_joined": counts[NOT_JOINED],
            "alerts_sent": self.alerts_sent, "goal_notifications": self.goal_notifications,
            "catchups": self.catchups, "stories": stories, "analyst_calls": analyst_calls, "llm_calls": llm_calls,
            "llm_calls_per_1000_fans": round(1000 * llm_calls / self.size, 2),
            "back_in_time": self.back_in_time,
            "grid": self.state.translate(bytes.maketrans(b"\x00\x01\x02\x03", b"0123")).decode(),
        }


def scaling_curve(meta: dict[str, Any], events: list[dict[str, Any]],
                  sizes: tuple[int, ...] = (1_000, 10_000, 50_000, 200_000)) -> list[dict[str, int]]:
    """Replay a match for audiences of growing size and report the LLM calls each needs."""
    from comeback.agents.analyst import needs_analyst
    from comeback.agents.brain import MatchBrain
    from comeback.agents.llm import LLMGateway, LLMMode, LLMSettings

    curve = []
    for size in sizes:
        brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
        crowd = Crowd(brain.engine, size)
        for event in events:
            crowd.on_event(brain.engine, brain.process(event), brain.cards)
        curve.append(crowd.cost(sum(1 for c in brain.cards.values() if needs_analyst(c))))
    return curve
