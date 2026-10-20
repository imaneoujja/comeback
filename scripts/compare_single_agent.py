"""Multi-agent pipeline vs ONE LLM agent that does everything at once.

Same inputs for both: the facts the match engine computes for every key moment, and
three fans (an analyst supporting the home side in French, a casual fan of the away
side in English, a Spanish fan following one striker who joins late).

* Single agent: one call per fan writes every moment card AND that fan's catch-up,
  with the same instructions about names and numbers, and no verification.
* COMEBACK: the Analyst writes each card once (shared by every fan), the rule-based
  Verifier checks it (rewrite ≤ 2, else template), one Storyteller call per catch-up.

Every text is then checked with the Verifier's rules (numbers and names must exist in
the facts, numerical advantage on the right team, nothing outside the match, no final
result before full time, length). For COMEBACK the delivered texts pass by
construction, so we also report the problems the Verifier caught in raw drafts.

Matches: the demo match + 2 unscripted matches. Replies are cached in
data/experiments/compare_cache.jsonl, so the numbers replay offline:

    python scripts/compare_single_agent.py              # offline, from the committed cache
    LLM_MODE=record python scripts/compare_single_agent.py   # re-run the experiment (~60 Foundry calls)
"""

import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comeback.agents.analyst import AnalystTask, AnalystWriter, needs_analyst, readable_facts  # noqa: E402
from comeback.agents.brain import MatchBrain  # noqa: E402
from comeback.agents.llm import DEFAULT_CACHE, LLMGateway, LLMMode, LLMSettings, LLMUnavailable, parse_json_reply  # noqa: E402
from comeback.agents.storyteller import WORD_LIMITS, CatchupTask, StorytellerWriter  # noqa: E402
from comeback.engine.match import load_match  # noqa: E402
from comeback.fans.catchup import build_delta, length_bucket, select_cards  # noqa: E402
from comeback.fans.profiles import FanProfile  # noqa: E402
from comeback.synth.cli import generate_random  # noqa: E402

CACHE = ROOT / "data" / "experiments" / "compare_cache.jsonl"
OUT = ROOT / "docs" / "single_agent_comparison.json"
SEEDS = (3001, 3002)
PRICE_IN, PRICE_OUT = 0.40, 1.60          # USD per 1M tokens, gpt-4.1-mini list price (Global Standard)
CHARS_PER_TOKEN = 4.0

SINGLE_AGENT_INSTRUCTIONS = """You are the AI of a football broadcast studio and companion app. The match,
clubs and players are fictional. You receive the computed facts of every key moment of a
match (with the match situation at that moment) and ONE fan profile with the window they
missed. In ONE answer, write JSON only:
{"cards": [{"moment": <index>, "headline": "...", "why_it_matters": "..."}], "catchup": "..."}
- cards: one per moment. headline: max 12 words, present tense, factual. why_it_matters:
  1-2 sentences (max 45 words) on WHY the moment matters (score, momentum, numerical
  advantage, storylines in the facts).
- catchup: what the fan missed, in their language, at their level (casual = simple words;
  analyst = tactical), from their side, within the word limit; explain what changed.
- Use ONLY names and numbers that appear in the input. Never invent events.
- Check players_on_pitch before mentioning a numerical advantage: the team with fewer
  players is the one that had a player sent off."""


class Gateway(LLMGateway):
    """The experiment's cache, with the demo's committed replies available too; counts calls and time."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if DEFAULT_CACHE.exists():
            for line in DEFAULT_CACHE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self.cache._data.setdefault(record["key"], record["text"])
        self.calls: list[dict[str, Any]] = []

    async def ask(self, agent_name: str, instructions: str, prompt: str):
        start = time.perf_counter()
        reply = await super().ask(agent_name, instructions, prompt)
        self.calls.append({"agent": agent_name, "in_chars": len(instructions) + len(prompt), "out_chars": len(reply.text),
                           "seconds": time.perf_counter() - start, "cached": reply.cached})
        return reply


def fans_for(meta: dict[str, Any]) -> list[tuple[FanProfile, float | None, float]]:
    """Three fans and their windows (second-half minutes; None = joined late)."""
    home, away = meta["home"]["id"], meta["away"]["id"]
    return [
        (FanProfile("a", "Omar", home, None, "analyst", "fr", "xg"), 63.0, 70.5),
        (FanProfile("b", "Sofia", away, None, "casual", "en", "possession"), 75.5, 86.0),
        (FanProfile("c", "Reda", None, f"{away}-9", "casual", "es", "top_speed"), None, 60.0),
    ]


def clock(e: dict[str, Any]) -> float:
    return e["minute"] + e["second"] / 60 if e["period"] == 2 else 0.0


async def run_match(name: str, meta: dict[str, Any], events: list[dict[str, Any]], gateway: Gateway) -> dict[str, Any]:
    brain = MatchBrain(meta, gateway)
    trace: list[dict[str, Any]] = []
    windows: dict[str, dict[str, Any]] = {}
    fans = fans_for(meta)
    started: dict[str, float] = {}
    for event in events:
        for moment in brain.process(event).moments:
            if brain.cards[moment.moment_id]["pending"]:
                await brain.write_card(moment, trace=trace.append)
        for fan, leave, back in fans:
            if leave is not None and fan.id not in started and clock(event) >= leave:
                started[fan.id] = event["t"]
            if fan.id not in windows and clock(event) >= back and (leave is None or fan.id in started):
                windows[fan.id] = {"from_t": started.get(fan.id, 0.0), "to_t": event["t"], "late": leave is None,
                                   "snapshot": brain.engine.snapshot()}
    st = brain.engine.state
    cards = sorted(brain.cards.values(), key=lambda c: c["t"])
    moments = [c for c in cards if needs_analyst(c)]

    # ---------------------------------------------------------------- COMEBACK: verified catch-ups
    ours_texts: list[dict[str, Any]] = [{"kind": "card", "source": c["source"]} for c in moments]
    for fan, _, _ in fans:
        w = windows[fan.id]
        out = await brain.catchup(fan, w["from_t"], w["to_t"], late_join=w["late"], trace=trace.append, snapshot=w["snapshot"])
        ours_texts.append({"kind": "catchup", "source": out["source"]})
    caught = Counter(rule_of(s["detail"]) for s in trace if s["step"] == "rejected")

    # ---------------------------------------------------------------- single agent: one call per fan
    single_texts, single_calls_before = [], len(gateway.calls)
    for fan, _, _ in fans:
        w = windows[fan.id]
        known = [c for c in moments if c["t"] <= w["to_t"]]      # only what had happened when the fan came back
        in_window = [c for c in cards if w["from_t"] <= c["t"] <= w["to_t"]]
        bucket = length_bucket(w["to_t"] - w["from_t"], w["late"])
        delta = build_delta(brain.engine.timeline, w["snapshot"], w["from_t"], st.team_names, in_window)
        payload = {
            "teams": list(st.team_names.values()),
            "moments": [{"index": i, "type": c["type"], "minute": c["minute"], "team": st.team_names.get(c["team"]),
                         "situation": brain._situations.get(c["moment_id"], {}),
                         "facts": readable_facts(c["facts"], st.team_names)} for i, c in enumerate(known)],
            "fan": {"first_name": fan.name, "language": {"en": "English", "fr": "French", "es": "Spanish"}[fan.language],
                    "level": fan.level, "supports": st.team_names.get(fan.club_id) if fan.club_id else None,
                    "favourite_player": st.roster.get(fan.favourite_player_id, {}).get("name")},
            "missed": {"joined_late": w["late"], "from_minute": delta["minute_then"], "to_minute": delta["minute_now"]},
            "delta": {k: v for k, v in delta.items() if k not in ("minute_then", "minute_now")},
            "word_limit": WORD_LIMITS[bucket],
        }
        try:
            reply = await gateway.ask("SingleAgent", SINGLE_AGENT_INSTRUCTIONS, json.dumps(payload, ensure_ascii=False))
            data = parse_json_reply(reply.text)
        except (LLMUnavailable, ValueError) as exc:
            single_texts.append({"kind": "error", "issues": [f"no usable reply: {exc}"]})
            continue
        written = {int(c.get("moment", -1)): c for c in data.get("cards", []) if isinstance(c, dict)}
        sa_cards, headlines = [], []
        for i, c in enumerate(known):
            out = written.get(i, {})
            if not out:                                  # a moment the agent did not write up: counted apart
                single_texts.append({"kind": "missing_card", "issues": []})
                sa_cards.append({**c, "headline": "", "why_it_matters": ""})
                continue
            task = AnalystTask(c, st.team_names, st.roster, list(headlines), brain._situations.get(c["moment_id"], {}))
            issues = AnalystWriter().verify(task, {"headline": str(out.get("headline", "")),
                                                   "why_it_matters": str(out.get("why_it_matters", ""))})
            single_texts.append({"kind": "card", "issues": issues})
            headlines.append(f"{c['minute']}' {out.get('headline', '')}")
            sa_cards.append({**c, "headline": str(out.get("headline", "")), "why_it_matters": str(out.get("why_it_matters", ""))})
        selected = select_cards([x for x in sa_cards if x["headline"]], w["from_t"], w["to_t"], fan, bucket)
        task = CatchupTask(fan, bucket, selected, delta, st.team_names, st.roster, w["late"], False)
        issues = StorytellerWriter().verify(task, {"text": str(data.get("catchup", ""))})
        single_texts.append({"kind": "catchup", "issues": issues})
    single_calls = gateway.calls[single_calls_before:]
    return {"match": name, "moments": len(moments), "ours": ours_texts, "caught": dict(caught),
            "single": single_texts, "single_calls": single_calls}


def rule_of(issue: str) -> str:
    """Group Verifier feedback into a few readable categories."""
    lowered = issue.lower()
    if "numbers are not in the facts" in lowered:
        return "invented or wrong number"
    if "numerical" in lowered or "short-handed" in lowered:
        return "numerical advantage on the wrong team"
    if "is not part of these facts" in lowered or "does not play in this match" in lowered:
        return "player or club not in the facts"
    if "match is not over" in lowered:
        return "result announced before full time"
    if "only talk about this match" in lowered:
        return "claim outside the match"
    if "missing" in lowered or "no usable" in lowered or "is empty" in lowered:
        return "missing or empty"
    if "characters long" in lowered:
        return "too long"
    return "other"


def cost(calls: list[dict[str, Any]]) -> float:
    return sum(c["in_chars"] / CHARS_PER_TOKEN * PRICE_IN + c["out_chars"] / CHARS_PER_TOKEN * PRICE_OUT
               for c in calls) / 1e6


async def main() -> None:
    mode = LLMMode(os.getenv("LLM_MODE", "offline").lower())
    settings = replace(LLMSettings.from_env(), mode=mode, cache_path=CACHE)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    gateway = Gateway(settings)
    matches = [("demo (scripted)", *load_match(ROOT / "data" / "matches" / "demo-comeback.jsonl"))]
    for seed in SEEDS:
        meta, *events = generate_random(seed)
        matches.append((f"unscripted #{seed}", meta, events))
    results = []
    for name, meta, events in matches:
        before = len(gateway.calls)
        result = await run_match(name, meta, events, gateway)
        result["ours_calls"] = [c for c in gateway.calls[before:] if c["agent"] != "SingleAgent"]
        results.append(result)
        print(f"{name}: {result['moments']} key moments · pipeline {len(result['ours_calls'])} calls · "
              f"single agent {len(result['single_calls'])} calls")

    single_all = [t for r in results for t in r["single"]]
    single = [t for t in single_all if t["kind"] != "missing_card"]
    missing = len(single_all) - len(single)
    single_bad = [t for t in single if t["issues"]]
    single_rules = Counter(rule_of(i) for t in single for i in t["issues"])
    ours = [t for r in results for t in r["ours"]]
    caught = Counter()
    for r in results:
        caught.update(r["caught"])
    ours_calls = [c for r in results for c in r["ours_calls"]]
    single_calls = [c for r in results for c in r["single_calls"]]
    scale = json.loads((ROOT / "data" / "scale" / "demo-comeback.json").read_text()) \
        if (ROOT / "data" / "scale" / "demo-comeback.json").exists() else None
    big = scale[-1] if scale else None
    per_call_ours = cost(ours_calls) / max(1, len(ours_calls))
    per_call_single = cost(single_calls) / max(1, len(single_calls))
    live = [c["seconds"] for c in ours_calls if not c["cached"]]
    live_single = [c["seconds"] for c in single_calls if not c["cached"]]
    report = {
        "matches": [r["match"] for r in results],
        "single_agent": {"texts": len(single), "texts_with_a_problem_delivered": len(single_bad),
                         "moments_left_without_a_card": missing, "moments_to_cover": len(single_all) - 3 * len(results),
                         "problems_by_rule": dict(single_rules), "calls": len(single_calls),
                         "usd_per_call": per_call_single,
                         "seconds_per_call_median": statistics.median(live_single) if live_single else None},
        "comeback": {"texts": len(ours), "texts_with_a_problem_delivered": 0,
                     "verified_llm_texts": sum(t["source"] == "llm" for t in ours),
                     "template_fallbacks": sum(t["source"] == "template" for t in ours),
                     "problems_caught_by_verifier": dict(caught), "calls": len(ours_calls), "usd_per_call": per_call_ours,
                     "seconds_per_call_median": statistics.median(live) if live else None},
    }
    if big:
        catchups = big["naive_llm_calls"] - (big["llm_calls"] - big["stories"])
        report["at_200k_fans_demo_match"] = {
            "fans": big["fans"], "comeback_calls": big["llm_calls"], "comeback_usd": big["llm_calls"] * per_call_ours,
            "single_agent_calls": catchups, "single_agent_usd": catchups * per_call_single}
    OUT.write_text(json.dumps(report, indent=1))
    s, o = report["single_agent"], report["comeback"]
    print("\n| | One LLM agent does everything | COMEBACK (Analyst → Verifier → Storyteller, shared brain) |")
    print("|---|---|---|")
    print(f"| Texts with a factual problem delivered to fans | **{s['texts_with_a_problem_delivered']} / {s['texts']}** "
          f"({s['texts_with_a_problem_delivered'] / max(1, s['texts']):.0%}) | **0 / {o['texts']}** ({o['template_fallbacks']} template fallbacks) |")
    print(f"| Key moments left without a card | {missing} of {s['moments_to_cover']} | 0 (every moment gets a card, "
          f"a template at once, the verified text when ready) |")
    print(f"| Problems found (Verifier rules) | {', '.join(f'{k}: {v}' for k, v in single_rules.most_common())} | "
          f"caught before air: {', '.join(f'{k}: {v}' for k, v in caught.most_common()) or 'none'} |")
    print(f"| LLM calls for {len(results)} matches × 3 fans | {s['calls']} (large) | {o['calls']} (small, cards shared) |")
    if big:
        b = report["at_200k_fans_demo_match"]
        print(f"| LLM calls for {b['fans']:,} fans (demo match) | {b['single_agent_calls']:,} | {b['comeback_calls']:,} |")
        print(f"| Cost for {b['fans']:,} fans (list price) | ${b['single_agent_usd']:,.0f} | ${b['comeback_usd']:,.2f} |")
    if s["seconds_per_call_median"] and o["seconds_per_call_median"]:
        print(f"| Latency | {s['seconds_per_call_median']:.1f} s per fan, after the window | template card at once, "
              f"verified card in {o['seconds_per_call_median']:.1f} s (median call) |")
    if mode is LLMMode.RECORD:
        print(f"Experiment cache: {gateway.cache.compact()} stale replies dropped")
    print(f"\n→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
