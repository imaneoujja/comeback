"""Evaluate the "come back" alert rule on unscripted synthetic matches.

Protocol (every number in the README comes from this script):

* Matches: unscripted synthetic matches only (no story beats; the scripted demo match
  is never used). Thresholds are tuned on seeds 1001-1050 and reported on held-out
  seeds 2001-2050 (``--first-seed``).
* Alert: the rule of ``comeback.engine.alerts`` (danger >= threshold, rising, not right
  after the team's own shot, cooldown), evaluated for both teams on every event.
* Precision: share of alerts followed by a shot with xG >= 0.1 by the same team within
  90 s. False alerts = the others.
* Recall (goal coverage): share of goals preceded by an alert for the scoring team within
  the anticipation window (5 minutes). Lead time = goal time - last such alert.
* Chance baselines: the SAME number of alerts placed at random instants (same teams),
  scored with the same definitions and averaged over 20 random draws; lift = ours / random.
* Alerts per fan: a 1,000-fan simulated audience per match (random absences, at most 2
  calls per absence), the same model as the AUDIENCE monitor.
* Latency: compute time from the event that pushes the danger over the threshold to the
  alert decision (engine update + rule), p50/p95.

Validated on synthetic data only; real-data validation is future work.

Usage:
    python scripts/evaluate_alerts.py                      # held-out matches, current threshold
    python scripts/evaluate_alerts.py --first-seed 1001    # the tuning matches
    python scripts/evaluate_alerts.py --curve              # threshold sweep + docs/alert_curve.svg
"""

import argparse
import json
import random
import statistics
import sys
import time
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comeback.engine.alerts import ANTICIPATION_S, AlertRule, AlertTracker  # noqa: E402
from comeback.engine.alerts import CHANCE_HORIZON_S as HORIZON_S  # noqa: E402
from comeback.engine.alerts import CHANCE_MIN_XG as MIN_XG  # noqa: E402
from comeback.engine.match import MatchEngine  # noqa: E402
from comeback.synth.cli import generate_random  # noqa: E402

CURVE = (30.0, 36.0, 40.0, 44.0, 48.0, 52.0, 55.0, 60.0, 65.0)
FANS_PER_MATCH = 1_000
RANDOM_DRAWS = 20


def evaluate_match(seed: int, thresholds: tuple[float, ...], rng: random.Random, fans: bool) -> dict:
    """Run the engine once on one match and score the rule at every threshold."""
    meta, *events = generate_random(seed)
    assert meta["scenario"] is None, "alert performance is measured on unscripted matches only"
    engine = MatchEngine(meta)
    teams = list(engine.danger)
    trackers = {th: {code: AlertTracker(AlertRule(threshold=th)) for code in teams} for th in thresholds}
    alerts: dict[float, list[tuple[float, str]]] = {th: [] for th in thresholds}
    latency_ms: list[float] = []
    for event in events:
        start = time.perf_counter()
        engine.process(event)
        state = {code: (*engine.danger_now(code), engine.state.seconds_since_shot(code)) for code in teams}
        decided = time.perf_counter()
        for th in thresholds:
            for code in teams:
                danger, slope, since_shot = state[code]
                if trackers[th][code].check(event["t"], danger, slope, since_shot):
                    alerts[th].append((event["t"], code))
                    if th == thresholds[0] or th == AlertRule.threshold:
                        latency_ms.append((decided - start) * 1000)
    chances = {code: sorted(e["t"] for e in events if e["type"] == "shot" and e["team"] == code and e["xg"] >= MIN_XG)
               for code in teams}
    goals = [(e["t"], e["team"]) for e in events if e["type"] == "shot" and e["outcome"] == "goal"]
    end_t = events[-1]["t"]

    def chance_after(t: float, code: str) -> float | None:
        times = chances[code]
        i = bisect_left(times, t + 1e-6)
        return times[i] - t if i < len(times) and times[i] - t <= HORIZON_S else None

    def score(points: list[tuple[float, str]]) -> dict:
        to_chance = [chance_after(t, c) for t, c in points]
        leads = []
        for t_goal, code in goals:
            before = [t for t, c in points if c == code and t_goal - ANTICIPATION_S <= t < t_goal]
            leads.append(t_goal - max(before) if before else None)
        return {"alerts": len(points), "hits": sum(x is not None for x in to_chance),
                "to_chance": [x for x in to_chance if x is not None], "leads": leads}

    out = {"goals": len(goals), "latency_ms": latency_ms, "by_threshold": {}}
    for th in thresholds:
        draws = [score([(rng.uniform(0, end_t), code) for _, code in alerts[th]]) for _ in range(RANDOM_DRAWS)]
        out["by_threshold"][th] = {"ours": [score(alerts[th])], "random": draws}
    if fans:
        out["alerts_per_fan"] = fans_alerts(meta, events, AlertRule.threshold)
    return out


def fans_alerts(meta: dict, events: list[dict], threshold: float) -> float:
    """Average call-backs one simulated fan receives in this match (absences as in the AUDIENCE model)."""
    from comeback.agents.brain import MatchBrain
    from comeback.agents.llm import LLMGateway, LLMMode, LLMSettings
    from comeback.fans.crowd import Crowd

    brain = MatchBrain(meta, LLMGateway(LLMSettings(mode=LLMMode.OFFLINE)))
    crowd = Crowd(brain.engine, FANS_PER_MATCH)
    crowd.trackers = {code: AlertTracker(AlertRule(threshold=threshold)) for code in crowd.trackers}
    for event in events:
        crowd.on_event(brain.engine, brain.process(event), brain.cards)
    return crowd.alerts_sent / FANS_PER_MATCH


def aggregate(results: list[dict], th: float) -> dict:
    rows = {}
    for side in ("ours", "random"):
        runs = [run for r in results for run in r["by_threshold"][th][side]]
        draws = len(runs) / len(results)                # 1 for ours, RANDOM_DRAWS for the baseline
        alerts = sum(run["alerts"] for run in runs)
        hits = sum(run["hits"] for run in runs)
        leads = [x for run in runs for x in run["leads"]]
        covered = [x for x in leads if x is not None]
        to_chance = [x for run in runs for x in run["to_chance"]]
        rows[side] = {
            "alerts": alerts / draws, "precision": hits / alerts if alerts else 0.0, "recall": len(covered) / len(leads),
            "goals": len(leads) / draws, "goals_announced": len(covered) / draws,
            "median_lead_s": statistics.median(covered) if covered else None,
            "median_alert_to_chance_s": statistics.median(to_chance) if to_chance else None,
            "false_alerts_per_match": (alerts - hits) / draws / len(results),
            "alerts_per_team_per_match": alerts / draws / (2 * len(results)),
        }
    return rows


def curve_svg(points: list[tuple[float, float, float]], chosen: float, path: Path) -> None:
    """Precision (y) vs recall (x), one dot per threshold; the chosen threshold highlighted."""
    w, h, pad = 520, 340, 46
    X = lambda r: pad + r * (w - 2 * pad)          # noqa: E731
    Y = lambda p: h - pad - p / 0.5 * (h - 2 * pad)  # noqa: E731 (precision axis 0-50%)
    dots, labels = [], []
    for th, rec, prec in points:
        hot = th == chosen
        dots.append(f'<circle cx="{X(rec):.1f}" cy="{Y(prec):.1f}" r="{6 if hot else 4}" fill="{"#ff3b30" if hot else "#ffb000"}"/>')
        labels.append(f'<text x="{X(rec) + 8:.1f}" y="{Y(prec) - 6:.1f}" fill="#ecebe6" font-size="11">{th:.0f}</text>')
    line = " ".join(f"{X(r):.1f},{Y(p):.1f}" for _, r, p in sorted(points, key=lambda q: q[1]))
    grid = "".join(f'<line x1="{X(i / 10):.1f}" y1="{pad}" x2="{X(i / 10):.1f}" y2="{h - pad}" stroke="#222"/>' for i in range(0, 11, 2))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="monospace">
<rect width="{w}" height="{h}" fill="#0b0b0b"/>{grid}
<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#666"/><line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h - pad}" stroke="#666"/>
<polyline points="{line}" fill="none" stroke="#ffb000" stroke-opacity=".5"/>{"".join(dots)}{"".join(labels)}
<text x="{w / 2}" y="{h - 12}" fill="#a09e97" font-size="12" text-anchor="middle">recall: goals announced within 5 min</text>
<text x="14" y="{h / 2}" fill="#a09e97" font-size="12" text-anchor="middle" transform="rotate(-90 14 {h / 2})">precision: chance (xG ≥ 0.1) within 90 s</text>
<text x="{pad}" y="24" fill="#ecebe6" font-size="13">Alert threshold sweep · held-out unscripted matches · red = chosen ({chosen:.0f})</text>
</svg>'''
    path.write_text(svg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matches", type=int, default=50)
    parser.add_argument("--first-seed", type=int, default=2001,
                        help="2001 = held-out matches (the threshold was tuned on seeds 1001-1050)")
    parser.add_argument("--threshold", type=float, default=AlertRule.threshold)
    parser.add_argument("--curve", action="store_true", help="also sweep thresholds and write docs/alert_curve.svg")
    parser.add_argument("--json", type=Path, default=ROOT / "docs" / "alerts_eval.json")
    args = parser.parse_args()

    thresholds = tuple(sorted(set((args.threshold, *CURVE)))) if args.curve else (args.threshold,)
    rng = random.Random(0)
    results = [evaluate_match(seed, thresholds, rng, fans=True)
               for seed in range(args.first_seed, args.first_seed + args.matches)]
    rows = aggregate(results, args.threshold)
    ours, rnd = rows["ours"], rows["random"]
    latency = sorted(x for r in results for x in r["latency_ms"])
    p50, p95 = latency[len(latency) // 2], latency[int(len(latency) * 0.95)]
    per_fan = statistics.mean(r["alerts_per_fan"] for r in results)
    rule = AlertRule(threshold=args.threshold)
    seeds = f"seeds {args.first_seed}-{args.first_seed + args.matches - 1}"
    print(f"Alert rule: danger >= {rule.threshold:.0f}, rising (+{rule.min_slope:.0f} over 30 s), not within "
          f"{rule.quiet_after_shot_s:.0f} s of the team's own shot, cooldown {rule.cooldown_s / 60:.0f} min · "
          f"{args.matches} unscripted matches ({seeds}) · {ours['goals']:.0f} goals\n")
    print("| Metric | COMEBACK | Same number of random alerts |")
    print("|---|---|---|")
    print(f"| Recall: goals announced by an alert for the scorer within 5 min | **{ours['recall']:.0%}** "
          f"({ours['goals_announced']:.0f}/{ours['goals']:.0f}) | {rnd['recall']:.0%} |")
    print(f"| Precision: alerts followed by a chance (xG >= {MIN_XG}) within {HORIZON_S:.0f} s | **{ours['precision']:.0%}** "
          f"| {rnd['precision']:.0%} |")
    print(f"| Lift over random (precision · recall) | ×{ours['precision'] / rnd['precision']:.1f} · "
          f"×{ours['recall'] / rnd['recall']:.1f} | ×1 |")
    print(f"| False alerts per match (both teams) | {ours['false_alerts_per_match']:.1f} | "
          f"{rnd['false_alerts_per_match']:.1f} |")
    print(f"| Alerts per team per match | {ours['alerts_per_team_per_match']:.1f} | same |")
    print(f"| Call-backs one fan actually receives per match (simulated absences, max 2 per absence) | {per_fan:.1f} | |")
    print(f"| Median warning before an announced goal | **{ours['median_lead_s']:.0f} s** | {rnd['median_lead_s']:.0f} s |")
    print(f"| Median time from an alert to the chance that follows | {ours['median_alert_to_chance_s']:.0f} s | |")
    print(f"| Decision latency (event → alert decision, compute) | p50 {p50:.2f} ms · p95 {p95:.2f} ms | |")
    report = {"protocol": __doc__, "seeds": seeds, "threshold": args.threshold, "rows": rows,
              "alerts_per_fan_per_match": per_fan, "latency_ms": {"p50": p50, "p95": p95}}
    if args.curve:
        print("\n| Threshold | Recall | Precision | Alerts / team / match | Lift (precision) |\n|---|---|---|---|---|")
        sweep = []
        for th in thresholds:
            r = aggregate(results, th)
            o, b = r["ours"], r["random"]
            sweep.append({"threshold": th, "recall": o["recall"], "precision": o["precision"],
                          "alerts_per_team_per_match": o["alerts_per_team_per_match"]})
            mark = " ← chosen" if th == args.threshold else ""
            print(f"| {th:.0f}{mark} | {o['recall']:.0%} | {o['precision']:.0%} | {o['alerts_per_team_per_match']:.1f} | "
                  f"×{o['precision'] / b['precision']:.1f} |")
        report["curve"] = sweep
        curve_svg([(s["threshold"], s["recall"], s["precision"]) for s in sweep], args.threshold, ROOT / "docs" / "alert_curve.svg")
        print("\n→ docs/alert_curve.svg")
    args.json.write_text(json.dumps(report, indent=1, default=float))
    print(f"→ {args.json.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
