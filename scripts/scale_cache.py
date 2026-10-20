"""Precompute the LLM-calls-vs-audience curve served by /api/scale (used at image build time).

Usage:
    python scripts/scale_cache.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comeback.engine.match import load_match  # noqa: E402
from comeback.fans.crowd import scaling_curve  # noqa: E402

SCALE_DIR = ROOT / "data" / "scale"


def main() -> None:
    SCALE_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted((ROOT / "data" / "matches").glob("*.jsonl")):   # every replayable match
        meta, events = load_match(path)
        curve = scaling_curve(meta, events)
        (SCALE_DIR / f"{path.stem}.json").write_text(json.dumps(curve))
        print(f"scale curve: {len(curve)} audience sizes → {SCALE_DIR / f'{path.stem}.json'}")


if __name__ == "__main__":
    main()
