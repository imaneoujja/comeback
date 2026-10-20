"""Precompute the replayable matches: Moment Cards and the scripted fans' catch-ups.

The scripted demo match gets neural voice-overs too; unscripted matches ("Try another
match") get their cards, the same fans' catch-ups and full-time recaps (browser voice).

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
from comeback.agents.speech import SpeechGateway  # noqa: E402
from comeback.agents.translator import english_version  # noqa: E402
from comeback.agents.watcher import Watcher  # noqa: E402
from comeback.engine.match import load_match  # noqa: E402
from comeback.fans.profiles import for_match, load_profiles  # noqa: E402
from comeback.fans.session import FanSession  # noqa: E402

MATCHES = Path(__file__).resolve().parents[1] / "data" / "matches"
DEMO = MATCHES / "demo-comeback.jsonl"
EXTRA_MATCHES = [MATCHES / "random-3112.jsonl"]   # "Try another match": unscripted

# (fan, leaves at match minute, comes back at match minute); None = late join at that minute.
SCRIPT = [("reda", None, 60.0), ("omar", 63.0, 70.5), ("sofia", 75.5, 86.0)]
# Extra late joins at 60' so the "Join at 60'" button has real text for every profile offline.
EXTRA_JOINS = ["omar", "sofia"]


async def precompute(path: Path, gateway: LLMGateway, speech: SpeechGateway | None) -> list[str | None]:
    """One match: every card, the scripted fans' catch-ups, extra late joins, full-time recaps."""
    meta, events = load_match(path)
    script = list(SCRIPT)
    voiced: list[str | None] = []

    async def voice(text: str, lang: str) -> None:
        voiced.append(await speech.audio_url(text, lang) if speech else None)
        await english_version(text, lang, gateway, brain.known_names())   # the "Show English" button

    brain = MatchBrain(meta, gateway)
    profiles = {pid: for_match(p, meta["home"]["id"], meta["away"]["id"]) for pid, p in load_profiles().items()}
    sessions = {fan: FanSession(profiles[fan]) for fan, _, _ in script}
    print(f"\n######## {meta['home']['name']} v {meta['away']['name']} ({path.stem})")
    watchers = {fan: Watcher(sessions[fan], brain.engine) for fan in sessions}

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
        for fan, leave, back in list(script):
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
                    await voice(result["text"], result["language"])
                    print(f"\n<<< {fan} {'joins' if leave is None else 'is back'} at {event['minute']}' "
                          f"[{result['bucket']}, {result['source']}, x{result['attempts']}]\n{result['text']}\n")
                script[:] = [s for s in script if s[0] != fan]
                if leave is None:
                    for extra in EXTRA_JOINS:
                        joined = await brain.catchup(profiles[extra], 0.0, event["t"], late_join=True)
                        await voice(joined["text"], joined["language"])
                        print(f"<<< {extra} joins at {event['minute']}' [{joined['source']}]: {joined['text'][:90]}…")
                break

    for fan in profiles:
        recap = await brain.final_recap(profiles[fan])
        await voice(recap["text"], recap["language"])
        print(f"\n=== {fan} full-time [{recap['source']}, x{recap['attempts']}] {recap['headline']}\n{recap['text']}")
    return voiced


async def main() -> None:
    gateway = LLMGateway()
    speech = SpeechGateway()
    print(f"LLM mode: {gateway.settings.mode.value}")
    voiced = await precompute(DEMO, gateway, speech)
    for path in EXTRA_MATCHES:
        await precompute(path, gateway, None)

    print(f"\nAudio: {sum(1 for v in voiced if v)}/{len(voiced)} spoken texts available (demo match)")
    print("Gateway stats:", json.dumps(dict(gateway.stats)))
    if "--compact" in sys.argv:
        print(f"Cache compacted: {gateway.cache.compact()} stale replies dropped")
        used = {Path(url).name for url in voiced if url}
        stale = [f for f in speech.audio_dir.glob("*.mp3") if f.name not in used]
        for f in stale:
            f.unlink()
        print(f"Audio compacted: {len(stale)} stale files removed")


if __name__ == "__main__":
    asyncio.run(main())
