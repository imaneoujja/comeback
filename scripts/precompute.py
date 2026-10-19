"""Precompute the demo match: Moment Cards and the scripted fans' catch-ups.

Run once with ``LLM_MODE=record`` (needs Foundry credentials) to fill
``data/llm_cache.jsonl``; the cache is committed so the demo then runs fully
offline with real LLM text. In ``offline`` mode it shows what judges will see.

Usage:
    LLM_MODE=record python scripts/precompute.py [--compact]

``--compact`` drops cached replies this run did not use (stale prompts).
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comeback.agents.brain import MatchBrain  # noqa: E402
from comeback.agents.llm import LLMGateway  # noqa: E402
from comeback.agents.watcher import Watcher  # noqa: E402
from comeback.engine.match import load_match  # noqa: E402
from comeback.fans.profiles import load_profiles  # noqa: E402
from comeback.fans.session import FanSession  # noqa: E402

DEMO = Path(__file__).resolve().parents[1] / "data" / "matches" / "demo-comeback.jsonl"

# (fan, leaves at match minute, comes back at match minute); None = late join at that minute.
SCRIPT = [("reda", None, 60.0), ("omar", 65.0, 70.5), ("sofia", 75.0, 86.0)]


async def main() -> None:
    meta, events = load_match(DEMO)
    gateway = LLMGateway()
    brain = MatchBrain(meta, gateway)
    profiles = load_profiles()
    sessions = {fan: FanSession(profiles[fan]) for fan, _, _ in SCRIPT}
    watchers = {fan: Watcher(sessions[fan], brain.engine) for fan in sessions}
    print(f"LLM mode: {gateway.settings.mode.value}\n")

    def clock(e: dict) -> float:
        return e["minute"] + e["second"] / 60

    for event in events:
        update = brain.process(event)
        for moment in update.moments:
            card = brain.cards[moment.moment_id]
            if card["pending"]:
                card = await brain.write_card(moment)
                print(f"[card {card['source']:8s} x{card['attempts']}] {card['minute']}' {card['type']}: "
                      f"{card['headline']}\n    {card['why_it_matters']}")
        for fan, leave, back in SCRIPT:
            session = sessions[fan]
            if event["period"] != 2:
                continue
            if leave is not None and session.present and session.away_since is None \
                    and not session.notifications and leave <= clock(event) < back:
                session.go_away(event["t"])
                print(f"\n>>> {fan} leaves at {event['minute']}:{event['second']:02d}")
            for note in watchers[fan].on_update(brain.engine, update):
                print(f"[{fan} phone] {note.minute}' {note.kind}: {note.text}")
            if clock(event) >= back and (leave is None or not session.present):
                window = session.come_back(event["t"]) if leave is not None else (0.0, event["t"])
                if window and (leave is None or window[0] > 0):
                    result = await brain.catchup(profiles[fan], *window, late_join=leave is None)
                    print(f"\n<<< {fan} {'joins' if leave is None else 'is back'} at {event['minute']}' "
                          f"[{result['bucket']}, {result['source']}, x{result['attempts']}]\n{result['text']}\n")
                SCRIPT[:] = [s for s in SCRIPT if s[0] != fan]
                break

    print("\nGateway stats:", json.dumps(dict(gateway.stats)))
    if "--compact" in sys.argv:
        print(f"Cache compacted: {gateway.cache.compact()} stale replies dropped")


if __name__ == "__main__":
    asyncio.run(main())
