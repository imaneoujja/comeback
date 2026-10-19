"""Evaluate the "come back" alert rule on unscripted synthetic matches.

For each alert (team danger >= threshold, rising, with cooldown) we check whether
the same team takes a shot with xG >= 0.1 within the next 60 s ("precision"),
and compare with a chance baseline: random instants in the same matches. We also
measure, for every goal, whether an alert for the scoring team came in the
previous 5 minutes ("goal coverage") and how early ("lead time").

Only unscripted matches are used (no story beats); the scripted demo match is
never part of these numbers. Validated on synthetic data only; real-data
validation is future work.

Usage:
    python scripts/evaluate_alerts.py [--matches 50] [--first-seed 1001]
"""

import argparse
import random
import statistics
import sys
from bisect import bisect_left
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comeback.engine.alerts import AlertRule, AlertTracker  # noqa: E402
from comeback.engine.match import MatchEngine  # noqa: E402
from comeback.synth.cli import generate_random  # noqa: E402

HORIZON_S = 60.0
MIN_XG = 0.1
GOAL_LOOKBACK_S = 300.0


def evaluate_match(seed: int, rule: AlertRule, rng: random.Random) -> dict[str, list]:
    """Run the engine on one match and collect alerts, chances and goals."""
    meta, *events = generate_random(seed)
    assert meta["scenario"] is None, "alert performance is measured on unscripted matches only"
    engine = MatchEngine(meta)
    trackers = {code: AlertTracker(rule) for code in engine.danger}
    alerts: list[tuple[float, str]] = []
    for event in events:
        engine.process(event)
        for code, tracker in trackers.items():
            danger, slope = engine.danger_now(code)
            if tracker.check(event["t"], danger, slope, engine.state.seconds_since_shot(code)):
                alerts.append((event["t"], code))
    chances = {code: sorted(e["t"] for e in events if e["type"] == "shot" and e["team"] == code
                            and e["xg"] >= MIN_XG) for code in trackers}
    goal_shots = [(e["t"], e["team"]) for e in events if e["type"] == "shot" and e["outcome"] == "goal"]

    def followed_by_chance(t: float, code: str) -> bool:
        times = chances[code]
        i = bisect_left(times, t + 1e-6)
        return i < len(times) and times[i] - t <= HORIZON_S

    end_t = events[-1]["t"]
    baseline = [followed_by_chance(rng.uniform(0, end_t), rng.choice(list(trackers))) for _ in range(200)]
    hits = [followed_by_chance(t, code) for t, code in alerts]
    leads = []
    for t_goal, code in goal_shots:
        before = [t for t, c in alerts if c == code and t_goal - GOAL_LOOKBACK_S <= t < t_goal]
        leads.append(t_goal - max(before) if before else None)
    return {"hits": hits, "baseline": baseline, "leads": leads}


def main() -> None:
    """Print the evaluation as a Markdown table (ready for the README)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matches", type=int, default=50)
    parser.add_argument("--first-seed", type=int, default=1001)
    parser.add_argument("--threshold", type=float, default=AlertRule.threshold)
    args = parser.parse_args()

    rule, rng = AlertRule(threshold=args.threshold), random.Random(0)
    hits, baseline, leads = [], [], []
    for seed in range(args.first_seed, args.first_seed + args.matches):
        result = evaluate_match(seed, rule, rng)
        hits += result["hits"]
        baseline += result["baseline"]
        leads += result["leads"]

    precision = sum(hits) / len(hits) if hits else 0.0
    base_rate = sum(baseline) / len(baseline)
    covered = [lead for lead in leads if lead is not None]
    print(f"Alert rule: danger >= {rule.threshold:.0f}, rising (slope >= {rule.min_slope:.0f} over 30 s), "
          f"not within {rule.quiet_after_shot_s:.0f} s of the team's own shot, cooldown "
          f"{rule.cooldown_s / 60:.0f} min — {args.matches} unscripted synthetic matches\n")
    print("| Metric | Value |")
    print("|---|---|")
    print(f"| Alerts per team per match | {len(hits) / (2 * args.matches):.1f} |")
    print(f"| Precision: alert followed by a shot with xG >= {MIN_XG} within {HORIZON_S:.0f} s | {precision:.0%} |")
    print(f"| Same, at a random instant (chance baseline) | {base_rate:.0%} |")
    print(f"| Lift over chance | x{precision / base_rate:.1f} |")
    print(f"| Goals preceded by an alert for the scoring team (5 min window) | "
          f"{len(covered)}/{len(leads)} ({len(covered) / len(leads):.0%}) |")
    if covered:
        print(f"| Median lead time before those goals | {statistics.median(covered):.0f} s |")


if __name__ == "__main__":
    main()
