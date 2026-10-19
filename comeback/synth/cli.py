"""Command-line entry point to generate synthetic match files.

Examples:
    python -m comeback.synth.cli demo
    python -m comeback.synth.cli random --count 20 --seed 1
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any

from comeback.synth.scenarios import SCENARIOS, Scenario
from comeback.synth.simulator import MatchSimulator, match_metadata
from comeback.synth.teams import CLUBS, build_fixture

DEFAULT_OUT_DIR = Path("data/matches")


def generate_match(home_id: str, away_id: str, *, seed: int, match_id: str,
                   scenario: Scenario | None = None) -> list[dict[str, Any]]:
    """Simulate a match and return its records: ``match_start`` metadata then events."""
    home, away = build_fixture(home_id, away_id, seed)
    meta = match_metadata(home, away, seed=seed, match_id=match_id, scenario=scenario)
    events = MatchSimulator(home, away, seed=seed, match_id=match_id, scenario=scenario).run()
    return [meta, *events]


def generate_scenario(match_id: str) -> list[dict[str, Any]]:
    """Generate one of the scripted matches in :data:`SCENARIOS`."""
    scenario = SCENARIOS[match_id]
    return generate_match(scenario.home, scenario.away, seed=scenario.seed,
                          match_id=match_id, scenario=scenario)


def generate_random(seed: int) -> list[dict[str, Any]]:
    """Generate an unscripted match between two clubs drawn from ``seed``."""
    home_id, away_id = random.Random(seed).sample(sorted(CLUBS), 2)
    return generate_match(home_id, away_id, seed=seed, match_id=f"random-{seed:04d}")


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """Write one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _summary(records: list[dict[str, Any]]) -> str:
    meta, events = records[0], records[1:]
    goals = [f"{e['minute']}' {e['team']} {e['score_home']}-{e['score_away']}"
             for e in events if e["type"] == "goal"]
    return f"{meta['home']['id']} vs {meta['away']['id']}: {len(events)} events, goals: {', '.join(goals) or 'none'}"


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and write match files."""
    parser = argparse.ArgumentParser(description="Generate synthetic football matches.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="generate the scripted demo match 'The Comeback'")
    rnd = sub.add_parser("random", help="generate unscripted matches")
    rnd.add_argument("--count", type=int, default=1)
    rnd.add_argument("--seed", type=int, default=1, help="seed of the first match")
    args = parser.parse_args(argv)

    if args.command == "demo":
        batches = [("demo-comeback", generate_scenario("demo-comeback"))]
    else:
        batches = [(f"random-{s:04d}", generate_random(s)) for s in range(args.seed, args.seed + args.count)]
    for match_id, records in batches:
        path = args.out / f"{match_id}.jsonl"
        write_jsonl(records, path)
        print(f"{path}  {_summary(records)}")


if __name__ == "__main__":
    main()
