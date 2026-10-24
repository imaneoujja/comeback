"""Precompute the agents' texts for every fan configuration of the playable matches.

A fan configures side (home / away / follow a player), language and style on the first
screen; the agents' texts for each combination are recorded once so the demo runs offline
with real model output:

* every Moment Card (shared by all fans);
* for each of the 18 configurations: the late join at 60', the returns of the two demo
  absences (63' → 70.5', the autoplay window, and 75.5' → 86'), and the full-time recap;
* an English version of every non-English text ("Show English");
* neural voice-overs for the demo match (autoplay return, late join, full-time recap).

Run once with ``LLM_MODE=record`` (needs Foundry credentials) to fill
``data/llm_cache.jsonl``; the cache is committed. In ``offline`` mode it shows what judges see.

Usage:
    LLM_MODE=record python scripts/precompute.py [--compact]

``--compact`` drops cached replies (and audio files) this run did not use.
"""

import asyncio
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comeback.agents.brain import MatchBrain  # noqa: E402
from comeback.agents.llm import LLMGateway  # noqa: E402
from comeback.agents.speech import SpeechGateway  # noqa: E402
from comeback.agents.translator import english_version  # noqa: E402
from comeback.engine.match import load_match  # noqa: E402
from comeback.fans.profiles import LANGUAGES, LEVELS, SIDES, fan_profile  # noqa: E402

MATCHES = Path(__file__).resolve().parents[1] / "data" / "matches"
PLAYABLE = [MATCHES / "demo-comeback.jsonl", MATCHES / "random-3112.jsonl"]
JOIN_AT = 60.0
ABSENCES = [(63.0, 70.5, True), (75.5, 86.0, False)]   # (leave, back, spoken on the demo match)


def clock(e: dict) -> float:
    return e["minute"] + e["second"] / 60 if e["period"] == 2 else 0.0


async def precompute(path: Path, gateway: LLMGateway, speech: SpeechGateway | None) -> list[str | None]:
    """One match: every card, every configuration's catch-ups and recap, translations, voices."""
    meta, events = load_match(path)
    home, away = meta["home"]["id"], meta["away"]["id"]
    fans = [fan_profile(side, lang, level, None, home, away)
            for side, lang, level in itertools.product(SIDES, LANGUAGES, LEVELS)]
    brain = MatchBrain(meta, gateway)
    voiced: list[str | None] = []
    stats = {"llm": 0, "template": 0}

    async def finish(result: dict, spoken: bool) -> None:
        stats[result["source"]] += 1
        text, lang = result["text"], result["language"]
        await english_version(text, lang, gateway, brain.known_names())     # the "Show English" button
        if speech and spoken:
            voiced.append(await speech.audio_url(text, lang))

    left: dict[float, float] = {}
    done: set[float] = set()
    joined = False
    print(f"\n######## {meta['home']['name']} v {meta['away']['name']} ({path.stem}) · {len(fans)} configurations")
    for event in events:
        for moment in brain.process(event).moments:
            if brain.cards[moment.moment_id]["pending"]:
                await brain.write_card(moment)
        m = clock(event)
        if not joined and m >= JOIN_AT:
            joined = True
            for fan in fans:
                await finish(await brain.catchup(fan, 0.0, event["t"], late_join=True), spoken=True)
        for leave, back, spoken in ABSENCES:
            if leave not in left and m >= leave:
                left[leave] = event["t"]
            if leave in left and back not in done and m >= back:
                done.add(back)
                for fan in fans:
                    await finish(await brain.catchup(fan, left[leave], event["t"]), spoken=spoken)
    for fan in fans:
        await finish(await brain.final_recap(fan), spoken=True)
    print(f"  catch-ups and recaps: {stats['llm']} verified LLM texts, {stats['template']} templates")
    return voiced


async def main() -> None:
    gateway = LLMGateway()
    speech = SpeechGateway()
    print(f"LLM mode: {gateway.settings.mode.value}")
    voiced = await precompute(PLAYABLE[0], gateway, speech)
    for path in PLAYABLE[1:]:
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
