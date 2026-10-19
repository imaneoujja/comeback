"""Possession-based football match simulator producing synthetic event streams.

Conventions:
    * Pitch is 105 x 68 m. The home team always attacks towards x = 105 and the
      away team towards x = 0, in **both** halves (no side switch, for simplicity).
    * Internally, positions are kept in the *attacking frame* of the team in
      possession (own goal at x = 0, target goal at x = 105) and converted to
      absolute pitch coordinates when an event is emitted.
    * ``t`` is elapsed seconds since kick-off (monotonic: first-half stoppage
      included, half-time break excluded). ``minute``/``second`` is the match
      clock shown on screen: the second half starts at 45:00 and stoppage time
      keeps counting (minute 92 = 90+2).
"""

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from comeback.engine.passes import completion_probability, pass_difficulty
from comeback.engine.xg import expected_goals, shot_geometry
from comeback.synth.scenarios import Beat, Scenario
from comeback.synth.teams import FORMATION_433, Player, Team

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
HALF_SECONDS = 45 * 60
CENTRE = (PITCH_LENGTH / 2, PITCH_WIDTH / 2)

# Calibration constant for pass completion (tuned against the realism targets).
PASS_MOD_BASE = 0.0
# Spells of dominance (unscripted matches): persistence per 30 s, noise, effect size.
SPELL_PERSISTENCE = 0.9
SPELL_NOISE = 0.3
SPELL_EFFECT = 0.8

STYLES: dict[str, dict[str, float]] = {
    "possession": {"pass_length": 10.0, "progression": 0.5, "press": 0.26, "carry": 0.17},
    "direct": {"pass_length": 16.0, "progression": 1.1, "press": 0.22, "carry": 0.15},
    "pressing": {"pass_length": 13.0, "progression": 0.8, "press": 0.38, "carry": 0.17},
    "balanced": {"pass_length": 13.0, "progression": 0.8, "press": 0.25, "carry": 0.18},
    "counter": {"pass_length": 15.0, "progression": 1.0, "press": 0.20, "carry": 0.23},
    "low_block": {"pass_length": 14.0, "progression": 0.8, "press": 0.16, "carry": 0.17},
}

_BENCH_REPLACES = {
    "DF": ("RB", "LB", "CB", "DF"),
    "MF": ("CDM", "CM", "CAM", "MF"),
    "FW": ("ST", "RW", "LW", "FW"),
}

Point = tuple[float, float]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _mirror(p: Point) -> Point:
    """Convert a point from one team's attacking frame to the other's."""
    return PITCH_LENGTH - p[0], PITCH_WIDTH - p[1]


def _in_box(p: Point) -> bool:
    return p[0] >= 88.5 and abs(p[1] - PITCH_WIDTH / 2) <= 20.16


@dataclass
class _Side:
    """Mutable in-match state of one team."""

    team: Team
    is_home: bool
    on_pitch: dict[str, Player]
    spots: dict[str, Point]
    bench: list[Player]
    yellow: set[str] = field(default_factory=set)
    score: int = 0

    @classmethod
    def from_team(cls, team: Team, is_home: bool) -> "_Side":
        return cls(
            team=team,
            is_home=is_home,
            on_pitch={p.id: p for p in team.starting_xi},
            spots={p.id: FORMATION_433[p.number] for p in team.starting_xi},
            bench=list(team.bench),
        )

    @property
    def code(self) -> str:
        return self.team.club.id

    @property
    def style(self) -> dict[str, float]:
        return STYLES[self.team.club.play_style]

    def by_positions(self, positions: tuple[str, ...], exclude: set[str] | None = None) -> list[str]:
        exclude = exclude or set()
        return [pid for pid, p in self.on_pitch.items() if p.position in positions and pid not in exclude]


class MatchSimulator:
    """Simulates one match and returns its events as a list of dicts."""

    def __init__(
        self,
        home: Team,
        away: Team,
        *,
        seed: int,
        match_id: str,
        scenario: Scenario | None = None,
    ) -> None:
        self.rng = random.Random(f"match:{seed}:{match_id}")
        self.match_id = match_id
        self.scenario = scenario
        self.sides = (_Side.from_team(home, True), _Side.from_team(away, False))
        self.events: list[dict[str, Any]] = []
        self.period = 1
        self.clock = 0.0
        self.t_offset = 0.0
        self.att = 0
        self.ball: Point = CENTRE
        self.holder = ""
        self.last_passer: str | None = None

        self.random_goals = scenario.random_goals if scenario else True
        if scenario and scenario.stoppage_minutes:
            self.stoppage = scenario.stoppage_minutes
        else:
            self.stoppage = (self.rng.randint(1, 4), self.rng.randint(2, 6))
        beats = scenario.beats if scenario else ()
        self.windows = [b for b in beats if b.kind == "momentum"]
        self.pending: list[Beat] = sorted((b for b in beats if b.kind != "momentum"), key=lambda b: b.minute)
        # Latent "spell" of dominance in unscripted matches (> 0 favours home), a
        # mean-reverting random walk updated every 30 s: real matches come in waves.
        self.spells = scenario is None
        self.latent = 0.0
        self._next_latent_t = 0.0
        self.sub_plan: list[tuple[float, int, str]] = []
        if scenario is None or scenario.random_substitutions:
            for idx in (0, 1):
                minutes = sorted(self.rng.uniform(56, 86) for _ in range(3))
                self.sub_plan += [(m, idx, kind) for m, kind in zip(minutes, ("FW", "MF", "DF"), strict=True)]
            self.sub_plan.sort()

    # ------------------------------------------------------------------ run

    def run(self) -> list[dict[str, Any]]:
        """Simulate the whole match."""
        for period in (1, 2):
            self._start_period(period)
            end = (HALF_SECONDS * period) + self.stoppage[period - 1] * 60 + self.rng.uniform(0, 30)
            while self.clock < end:
                self._apply_due_events()
                self._play_action()
            self._emit("period_end", None, None)
            if period == 1:
                self.t_offset = self.clock - HALF_SECONDS
        home, away = self.sides
        self._emit("match_end", None, None, score_home=home.score, score_away=away.score)
        return self.events

    def _start_period(self, period: int) -> None:
        self.period = period
        self.clock = HALF_SECONDS * (period - 1)
        self._kickoff(0 if period == 1 else 1)
        self._emit("period_start", self.sides[self.att].code, None)

    def _kickoff(self, idx: int) -> None:
        self.att = idx
        self.ball = CENTRE
        side = self.sides[idx]
        self.holder = (side.by_positions(("CM", "CAM", "MF", "CDM")) or list(side.on_pitch))[0]
        self.last_passer = None

    # --------------------------------------------------------------- events

    def _emit(self, etype: str, team: str | None, player: str | None, pos: Point | None = None,
              end: Point | None = None, **fields: Any) -> dict[str, Any]:
        """Append an event. ``pos``/``end`` are in the possessing team's attacking frame."""
        event: dict[str, Any] = {
            "id": f"e{len(self.events) + 1:06d}",
            "match_id": self.match_id,
            "t": round(self.clock + self.t_offset, 1),
            "period": self.period,
            "minute": int(self.clock // 60),
            "second": int(self.clock % 60),
            "type": etype,
            "team": team,
            "player": player,
        }
        if pos is not None:
            event["x"], event["y"] = self._to_abs(pos)
        if end is not None:
            event["end_x"], event["end_y"] = self._to_abs(end)
        event.update(fields)
        self.events.append(event)
        return event

    def _to_abs(self, p: Point) -> tuple[float, float]:
        x, y = p if self.sides[self.att].is_home else _mirror(p)
        return round(x, 1), round(y, 1)

    # -------------------------------------------------------- team context

    def _minute(self) -> float:
        return self.clock / 60

    def _momentum(self, idx: int) -> float:
        code, minute = self.sides[idx].code, self._minute()
        scripted = sum(
            w.strength for w in self.windows
            if w.team == code and w.minute <= minute < (w.until_minute or w.minute)
        )
        spell = max(0.0, self.latent if idx == 0 else -self.latent)
        return scripted + SPELL_EFFECT * spell

    def _update_latent(self) -> None:
        while self.spells and self.clock >= self._next_latent_t:
            self.latent = _clip(self.latent * SPELL_PERSISTENCE + self.rng.gauss(0, SPELL_NOISE), -1.2, 1.2)
            self._next_latent_t = self.clock + 30

    def _team_mod(self, idx: int) -> float:
        side, opp = self.sides[idx], self.sides[1 - idx]
        mod = PASS_MOD_BASE + (side.team.club.strength - 72) / 40 + (0.08 if side.is_home else 0.0)
        mod += 0.3 * (len(side.on_pitch) - len(opp.on_pitch))
        return mod + 0.7 * self._momentum(idx) - 0.4 * self._momentum(1 - idx)

    def _teammate_pos(self, pid: str) -> Point:
        side = self.sides[self.att]
        sx, sy = side.spots[pid]
        bx, by = self.ball
        if side.on_pitch[pid].position == "GK":
            return sx + max(0.0, bx - 50) * 0.1, sy
        x = sx + (bx - 45) * 0.45 + self.rng.gauss(0, 3)
        y = sy + (by - sy) * 0.2 + self.rng.gauss(0, 3)
        return _clip(x, 2, min(95.0, max(84.0, bx + 6))), _clip(y, 1, 67)

    def _opponent_pos(self, pid: str) -> Point:
        mx, my = _mirror(self.sides[1 - self.att].spots[pid])
        bx, by = self.ball
        return mx + (bx - mx) * 0.3, my + (by - my) * 0.3

    def _nearest_opponent(self, point: Point) -> str:
        opp = self.sides[1 - self.att]
        best, best_d = "", float("inf")
        for pid, p in opp.on_pitch.items():
            if p.position == "GK" and point[0] < 95:
                continue
            d = _dist(self._opponent_pos(pid), point) + self.rng.gauss(0, 2.5)
            if d < best_d:
                best, best_d = pid, d
        return best

    # -------------------------------------------------------------- actions

    def _play_action(self) -> None:
        self._update_latent()
        side, opp = self.sides[self.att], self.sides[1 - self.att]
        if self.holder not in side.on_pitch:
            self.holder = min(side.on_pitch, key=lambda pid: _dist(self._teammate_pos(pid), self.ball))
        holder = side.on_pitch[self.holder]

        under_pressure = False
        press_p = opp.style["press"] * (1.3 if self.ball[0] < 40 and opp.team.club.play_style == "pressing" else 1.0)
        press_p += 0.1 * self._momentum(1 - self.att)
        if holder.position != "GK" and self.rng.random() < press_p:
            defender = self._nearest_opponent(self.ball)
            success = self.rng.random() < 0.35
            self._emit("pressure", opp.code, defender, self.ball, target_player=holder.id, success=success)
            self.clock += 0.5
            if success:
                under_pressure = True
                if self.rng.random() < 0.35 and self._tackle(defender):
                    return

        r = self.rng.random()
        shot_p = self._shot_probability(holder)
        winger_boost = 1.6 if holder.position in ("RW", "LW") else 1.0
        carry_p = 0.0 if holder.position == "GK" else side.style["carry"] * winger_boost
        if r < shot_p:
            self._shoot(holder)
        elif r < shot_p + carry_p:
            self._carry(holder, under_pressure)
        else:
            self._pass(holder, under_pressure)

    def _shot_probability(self, holder: Player) -> float:
        if holder.position == "GK":
            return 0.0
        distance, _ = shot_geometry(*self.ball)
        if _in_box(self.ball):
            p = 0.095 if distance < 14 else 0.085
        elif distance < 25:
            p = 0.052
        elif distance < 32:
            p = 0.025
        else:
            return 0.0
        return min(0.9, p * (1 + self._momentum(self.att)))

    def _choose_receiver(self, holder: Player) -> tuple[str, Point]:
        side = self.sides[self.att]
        ax = self.ball[0]
        candidates: list[tuple[str, Point]] = []
        weights: list[float] = []
        for pid, p in side.on_pitch.items():
            if pid == holder.id:
                continue
            pos = self._teammate_pos(pid)
            d = _dist(pos, self.ball)
            if d < 5:
                continue
            dx = pos[0] - ax
            w = math.exp(-d / side.style["pass_length"])
            if dx > 0:
                w *= 1 + side.style["progression"] * min(dx, 30) / 15
            elif dx < -8:
                w *= 0.55
            if p.position == "GK":
                w *= 0.6 if ax < 35 else 0.02
            candidates.append((pid, pos))
            weights.append(w)
        if not candidates:
            pid = next(pid for pid in side.on_pitch if pid != holder.id)
            return pid, self._teammate_pos(pid)
        return candidates[self.rng.choices(range(len(candidates)), weights)[0]]

    def _pass(self, holder: Player, under_pressure: bool, receiver: str | None = None,
              target: Point | None = None, force: bool | None = None, cross: bool = False) -> bool:
        """Play a pass; returns True if completed."""
        side = self.sides[self.att]
        if receiver is None:
            receiver, target = self._choose_receiver(holder)
        elif target is None:
            target = self._teammate_pos(receiver)
        start = self.ball
        distance = max(1.0, _dist(start, target))
        dx = target[0] - start[0]
        forward_ratio = max(0.0, dx) / distance
        difficulty = pass_difficulty(distance, under_pressure, forward_ratio, target[0] >= 70)
        p = completion_probability(holder.passing, difficulty, self._team_mod(self.att))
        success = force if force is not None else self.rng.random() < p
        if success:
            end = target
        else:
            frac = self.rng.uniform(0.45, 1.0)
            end = (_clip(start[0] + dx * frac + self.rng.gauss(0, 3), 0.5, 104.5),
                   _clip(start[1] + (target[1] - start[1]) * frac + self.rng.gauss(0, 3), 0.5, 67.5))
        speed = _clip(28 + 1.25 * distance + self.rng.gauss(0, 5), 18, 105)
        self._emit(
            "pass", side.code, holder.id, start, end,
            receiver=receiver, distance_m=round(distance, 1), difficulty=round(difficulty),
            success=success, under_pressure=under_pressure,
            progressive=dx >= max(10.0, 0.25 * (PITCH_LENGTH - start[0])),
            ball_speed_kmh=round(speed, 1), cross=cross,
        )
        self.clock += 1.0 + distance / (speed / 3.6) + self.rng.uniform(0.5, 2.2)
        if success:
            self.last_passer, self.holder, self.ball = holder.id, receiver, end
            return True

        self.last_passer = None
        if self.rng.random() < 0.18:
            if end[0] > 101 and self.rng.random() < 0.35:
                self._corner()
            elif end[0] > 101:
                self._goal_kick(1 - self.att)
            else:
                self._throw_in(1 - self.att, (end[0], 0.0 if end[1] < PITCH_WIDTH / 2 else PITCH_WIDTH))
        else:
            defender = self._nearest_opponent(end)
            self._emit("interception", self.sides[1 - self.att].code, defender, end)
            self._turnover(defender, "interception", end)
        return False

    def _carry(self, holder: Player, under_pressure: bool, target: Point | None = None,
               speed: float | None = None) -> None:
        start = self.ball
        if target is None:
            if start[0] < 85 and not under_pressure and self.rng.random() < 0.3:
                length = self.rng.uniform(12, 30)
                speed = holder.top_speed_kmh * self.rng.uniform(0.8, 0.99)
            else:
                length = self.rng.uniform(3, 10)
                speed = self.rng.uniform(9, 19) + (holder.pace - 60) * 0.05
            angle = self.rng.gauss(0, 0.55)
            target = (_clip(start[0] + length * math.cos(angle), 1, 103),
                      _clip(start[1] + length * math.sin(angle) + (PITCH_WIDTH / 2 - start[1]) * 0.08, 1, 67))
        speed = speed or holder.top_speed_kmh * 0.9
        length = _dist(start, target)
        code = self.sides[self.att].code
        self._emit("carry", code, holder.id, start, target, speed_kmh=round(speed, 1))
        if speed > 30:
            self._emit("sprint", code, holder.id, start, target,
                       speed_kmh=round(speed, 1), distance_m=round(length, 1))
        self.clock += length / (speed / 3.6) + 0.5
        self.ball = target
        if self.rng.random() < 0.12:
            self._tackle(self._nearest_opponent(self.ball))

    def _tackle(self, defender_id: str) -> bool:
        """A defender challenges the ball carrier. Returns True if play stopped or possession changed."""
        side, opp = self.sides[self.att], self.sides[1 - self.att]
        holder, defender = side.on_pitch[self.holder], opp.on_pitch[defender_id]
        if self.rng.random() < (0.015 if _in_box(self.ball) else 0.24):
            self._foul(defender_id, holder.id)
            return True
        won = self.rng.random() < _clip(0.45 + (defender.defending - holder.pace) / 200, 0.2, 0.75)
        self._emit("tackle", opp.code, defender_id, self.ball, opponent=holder.id, won=won)
        self.clock += 1.5
        if won:
            self._turnover(defender_id, "tackle", self.ball)
        return won

    def _turnover(self, new_holder: str, reason: str, point: Point) -> None:
        """Give the ball to the other team at ``point`` (current attacking frame)."""
        from_code = self.sides[self.att].code
        self.att = 1 - self.att
        self.ball = _mirror(point)
        self.holder, self.last_passer = new_holder, None
        to_code = self.sides[self.att].code
        self._emit("possession_change", to_code, new_holder, self.ball,
                   from_team=from_code, to_team=to_code, reason=reason)
        self.clock += 1.0

    def _foul(self, offender: str, victim: str, card: str | None = None, reason: str | None = None) -> None:
        """Foul by the defending team; ``card`` forces a card colour."""
        opp_idx = 1 - self.att
        opp = self.sides[opp_idx]
        penalty = _in_box(self.ball)
        self._emit("foul", opp.code, offender, self.ball, opponent=victim, penalty=penalty)
        if card is None and self.rng.random() < 0.17:
            card = "red" if offender in opp.yellow else "yellow"
        if card:
            fields: dict[str, Any] = {"color": card}
            if reason:
                fields["reason"] = reason
            if card == "red" and offender in opp.yellow:
                fields["second_yellow"] = True
            self._emit("card", opp.code, offender, self.ball, **fields)
            if card == "yellow":
                opp.yellow.add(offender)
            else:
                del opp.on_pitch[offender]
                del opp.spots[offender]
        self.clock += self.rng.uniform(20, 40)
        if penalty:
            side = self.sides[self.att]
            taker = max(side.on_pitch.values(), key=lambda p: p.finishing)
            self.holder, self.ball, self.last_passer = taker.id, (94.0, 34.0), None
            self.clock += 30
            self._shoot(taker, body_part="penalty")

    def _shoot(self, shooter: Player, body_part: str | None = None, forced: str | None = None) -> None:
        side = self.sides[self.att]
        distance, angle = shot_geometry(*self.ball)
        if body_part == "penalty":
            xg = 0.76
        else:
            body_part = body_part or self.rng.choice(("right_foot", "right_foot", "left_foot"))
            xg = expected_goals(distance, angle, header=body_part == "head")
        if body_part == "head":
            speed = self.rng.uniform(55, 75)
        else:
            speed = 120 - 1.2 * distance + (shooter.finishing - 60) * 0.25 + self.rng.gauss(0, 8)
        if forced:
            outcome = forced
        elif self.rng.random() < xg * (0.75 + shooter.finishing / 280):
            outcome = "goal" if self.random_goals else "saved"
        else:
            u = self.rng.random()
            outcome = "blocked" if u < 0.27 else "saved" if u < 0.6 else "off_target"
        if body_part == "penalty" and outcome == "blocked":
            outcome = "saved"
        self._emit("shot", side.code, shooter.id, self.ball, xg=round(xg, 3),
                   shot_speed_kmh=round(_clip(speed, 55, 125), 1), outcome=outcome, body_part=body_part)
        self.clock += 2.0

        if outcome == "goal":
            self._goal(shooter)
        elif outcome == "saved":
            if self.rng.random() < 0.4:
                self._corner()
            else:
                gk = self.sides[1 - self.att].by_positions(("GK",))[0]
                self._turnover(gk, "save", (100.0, 34.0))
                self.clock += self.rng.uniform(4, 10)
        elif outcome == "blocked":
            if self.rng.random() < 0.5:
                self._corner()
            else:
                defender = self._nearest_opponent(self.ball)
                self._turnover(defender, "block", self.ball)
        else:
            self._goal_kick(1 - self.att)

    def _goal(self, scorer: Player) -> None:
        side = self.sides[self.att]
        side.score += 1
        home, away = self.sides
        assist = self.last_passer if self.last_passer != scorer.id else None
        self._emit("goal", side.code, scorer.id, self.ball, scorer=scorer.id, assist=assist,
                   score_home=home.score, score_away=away.score)
        self.clock += self.rng.uniform(50, 80)
        self._kickoff(1 - self.att)

    def _corner(self) -> None:
        side = self.sides[self.att]
        corner = (104.5, 0.5 if self.rng.random() < 0.5 else 67.5)
        taker_id = (side.by_positions(("RW", "LW", "CAM")) or list(side.on_pitch))[0]
        self.ball, self.holder = corner, taker_id
        self._emit("corner", side.code, taker_id, corner)
        self.clock += self.rng.uniform(20, 35)
        targets = side.by_positions(("CB", "ST", "FW", "CAM", "DF"), exclude={taker_id}) or [
            pid for pid in side.on_pitch if pid != taker_id]
        target_id = self.rng.choice(targets)
        target = (self.rng.uniform(94, 100), self.rng.uniform(28, 40))
        completed = self._pass(side.on_pitch[taker_id], True, target_id, target, cross=True)
        if completed and self.rng.random() < 0.65:
            self._shoot(side.on_pitch[target_id], body_part="head")

    def _throw_in(self, idx: int, point: Point) -> None:
        """Throw-in for team ``idx`` at ``point`` (current attacking frame)."""
        side = self.sides[idx]
        taker = (side.by_positions(("RB", "LB", "DF")) or list(side.on_pitch))[0]
        if idx != self.att:
            self._turnover(taker, "out_of_play", point)
        self.holder = taker
        self._emit("throw_in", side.code, taker, self.ball)
        self.clock += self.rng.uniform(8, 18)

    def _goal_kick(self, idx: int) -> None:
        side = self.sides[idx]
        gk = side.by_positions(("GK",))[0]
        if idx != self.att:
            self._turnover(gk, "out_of_play", (100.0, 34.0))
        self.holder, self.ball = gk, (5.5, 34.0 + self.rng.choice((-9.0, 9.0)))
        self._emit("goal_kick", side.code, gk, self.ball)
        self.clock += self.rng.uniform(15, 30)

    # ------------------------------------------------- substitutions & beats

    def _apply_due_events(self) -> None:
        minute = self._minute()
        while self.sub_plan and self.sub_plan[0][0] <= minute and self.period == 2:
            _, idx, kind = self.sub_plan.pop(0)
            self._random_substitution(idx, kind)
        while self.pending and self._beat_due(self.pending[0]):
            self._fire(self.pending.pop(0))

    def _beat_due(self, beat: Beat) -> bool:
        in_period = (beat.minute < 45) == (self.period == 1)
        return in_period and self.clock >= beat.minute * 60

    def _random_substitution(self, idx: int, kind: str) -> None:
        side = self.sides[idx]
        incoming = next((p for p in side.bench if p.position == kind), None)
        candidates = side.by_positions(_BENCH_REPLACES[kind], exclude={p.id for p in side.team.bench})
        if incoming and candidates:
            self._substitute(idx, self.rng.choice(candidates), incoming.id)

    def _substitute(self, idx: int, out_id: str, in_id: str, spot: Point | None = None,
                    formation: str | None = None) -> None:
        side = self.sides[idx]
        if out_id not in side.on_pitch:
            return
        incoming = next(p for p in side.bench if p.id == in_id)
        side.bench.remove(incoming)
        side.on_pitch[in_id] = incoming
        side.spots[in_id] = spot or side.spots[out_id]
        del side.on_pitch[out_id], side.spots[out_id]
        if self.holder == out_id:
            self.holder = in_id
        fields: dict[str, Any] = {"player_in": in_id, "player_out": out_id}
        if formation:
            fields["formation"] = formation
        if spot:
            fields["spot"] = list(spot)
        self._emit("substitution", side.code, out_id, **fields)
        self.clock += self.rng.uniform(20, 35)

    def _side_index(self, code: str) -> int:
        return 0 if self.sides[0].code == code else 1

    def _fire(self, beat: Beat) -> None:
        idx = self._side_index(beat.team)
        if beat.kind == "goal":
            self._scripted_attack(idx, beat.player, "goal")
        elif beat.kind == "big_chance_missed":
            self._scripted_attack(idx, beat.player, "saved")
        elif beat.kind == "red_card" and beat.player:
            if self.att == idx:
                opp = self.sides[1 - idx]
                winner = (opp.by_positions(("CM", "CAM", "MF")) or list(opp.on_pitch))[0]
                self._turnover(winner, "interception", self.ball)
            self.ball = (self.rng.uniform(70, 80), self.rng.uniform(25, 43))
            victim = (self.sides[self.att].by_positions(("ST", "FW", "RW", "LW")) or [self.holder])[0]
            self.holder = victim
            self._foul(beat.player, victim, card="red", reason="denying an obvious goal-scoring opportunity")
        elif beat.kind == "shape_change" and beat.player and beat.player_in:
            self._substitute(idx, beat.player, beat.player_in, spot=(78.0, 26.0), formation=beat.formation)

    def _scripted_attack(self, idx: int, shooter_id: str | None, outcome: str) -> None:
        """Force a flowing attack that ends with a shot by ``shooter_id`` with a given outcome."""
        side = self.sides[idx]
        if self.att != idx:
            winner = (side.by_positions(("CDM", "CM", "MF", "CAM")) or list(side.on_pitch))[0]
            point = _mirror((self.rng.uniform(47, 55), self.rng.uniform(20, 48)))
            self.ball = point
            self._emit("interception", side.code, winner, point)
            self._turnover(winner, "interception", point)
        if shooter_id not in side.on_pitch:
            shooter_id = (side.by_positions(("ST", "FW")) or [self.holder])[0]
        used = {shooter_id}
        mids = side.by_positions(("CAM", "CM", "MF", "CDM"), exclude=used | {self.holder})
        wide = side.by_positions(("RW", "LW", "FW", "RB", "LB"), exclude=used | {self.holder})
        chain = [m for m in (mids[:1] + wide[:1]) if m]
        flank = self.rng.choice((10.0, 58.0))
        targets = [(self.rng.uniform(62, 68), self.rng.uniform(25, 43)), (self.rng.uniform(80, 86), flank)]
        for receiver, target in zip(chain, targets, strict=False):
            self._pass(self.sides[idx].on_pitch[self.holder], False, receiver, target, force=True)
        carrier = side.on_pitch[self.holder]
        self._carry(carrier, False, target=(self.rng.uniform(92, 96), flank + (6 if flank < 34 else -6)),
                    speed=max(31.0, carrier.top_speed_kmh * 0.95))
        if self.holder != shooter_id:
            shot_spot = (self.rng.uniform(96, 99), self.rng.uniform(31, 37))
            self._pass(carrier, False, shooter_id, shot_spot, force=True)
        self._shoot(side.on_pitch[shooter_id], forced=outcome)


def match_metadata(home: Team, away: Team, *, seed: int, match_id: str,
                   scenario: Scenario | None) -> dict[str, Any]:
    """First line of a match file: fixture, rosters, scenario and conventions."""

    def team_dict(team: Team) -> dict[str, Any]:
        starters = {p.id for p in team.starting_xi}
        players = [{**asdict(p), "spot": list(FORMATION_433[p.number]) if p.id in starters else None}
                   for p in team.players]
        return {**asdict(team.club), "players": players,
                "starting_xi": [p.id for p in team.starting_xi], "formation": "4-3-3"}

    return {
        "type": "match_start",
        "match_id": match_id,
        "seed": seed,
        "home": team_dict(home),
        "away": team_dict(away),
        "pitch": {"length_m": PITCH_LENGTH, "width_m": PITCH_WIDTH,
                  "direction": "home attacks towards x=105 and away towards x=0 in both halves"},
        "scenario": asdict(scenario) if scenario else None,
    }
