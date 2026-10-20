"""Evaluate every text the fans see with Microsoft Foundry evaluators (azure-ai-evaluation).

Replays the demo offline, records the exact prompt (the facts) behind each final
verified text, then scores it with Foundry's AI-assisted evaluators:
groundedness (against those facts), coherence and fluency, on a 1-5 scale.
The judge is the project's Foundry deployment (FOUNDRY_* in .env).

Usage:
    pip install -r requirements-extras.txt
    python scripts/evaluate_texts.py            # writes docs/evaluation.json, prints a table
"""

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from azure.ai.evaluation import CoherenceEvaluator, FluencyEvaluator, GroundednessEvaluator  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from comeback.agents.brain import MatchBrain  # noqa: E402
from comeback.agents.llm import LLMGateway, LLMMode, LLMReply, LLMSettings, parse_json_reply  # noqa: E402
from comeback.engine.match import load_match  # noqa: E402
from comeback.fans.profiles import load_profiles  # noqa: E402

OUT = ROOT / "docs" / "evaluation.json"
QUERIES = {
    "Analyst": "Write a headline and explain why this football moment matters, using only the given facts.",
    "Storyteller": "Tell this fan what happened while they were away, in their language and from their side.",
}
SCRIPT = [("reda", None, 60.0), ("omar", 63.0, 70.5), ("sofia", 75.5, 86.0)]


class RecordingGateway(LLMGateway):
    """Offline gateway that remembers every (agent, prompt, reply) it serves."""

    def __init__(self) -> None:
        super().__init__(LLMSettings(mode=LLMMode.OFFLINE))
        self.records: list[tuple[str, str, str]] = []

    async def ask(self, agent_name: str, instructions: str, prompt: str) -> LLMReply:
        reply = await super().ask(agent_name, instructions, prompt)
        self.records.append((agent_name, prompt, reply.text))
        return reply


def _prompt_for(records: list[tuple[str, str, str]], agent: str, key: str, value: str) -> str | None:
    for name, prompt, text in reversed(records):
        if name != agent:
            continue
        try:
            if str(parse_json_reply(text).get(key, "")).strip() == value:
                return prompt
        except ValueError:
            continue
    return None


async def collect() -> list[dict]:
    """Final verified LLM texts of the demo, each with the facts it was written from."""
    meta, events = load_match(ROOT / "data" / "matches" / "demo-comeback.jsonl")
    gateway = RecordingGateway()
    brain = MatchBrain(meta, gateway)
    profiles = load_profiles()
    away: dict[str, float] = {}
    texts: list[dict] = []
    for event in events:
        for moment in brain.process(event).moments:
            if brain.cards[moment.moment_id]["pending"]:
                await brain.write_card(moment)
        if event["period"] != 2:
            continue
        clock = event["minute"] + event["second"] / 60
        for fan, leave, back in SCRIPT:
            if leave is not None and fan not in away and leave <= clock < back:
                away[fan] = event["t"]
            if clock >= back and away.get(fan, 0) != -1:
                start = 0.0 if leave is None else away[fan]
                result = await brain.catchup(profiles[fan], start, event["t"], late_join=leave is None)
                texts.append({"kind": "catch-up", "agent": "Storyteller", "fan": fan, "text": result["text"],
                              "source": result["source"]})
                away[fan] = -1
    for fan in profiles:
        recap = await brain.final_recap(profiles[fan])
        texts.append({"kind": "full-time recap", "agent": "Storyteller", "fan": fan,
                      "text": f"{recap['headline']}\n{recap['text']}", "body": recap["text"],
                      "source": recap["source"]})
    for card in brain.cards.values():
        if card["source"] == "llm":
            texts.append({"kind": "moment card", "agent": "Analyst", "moment": f"{card['minute']}' {card['type']}",
                          "text": f"{card['headline']}\n{card['why_it_matters']}", "headline": card["headline"],
                          "source": "llm"})
    for t in texts:
        if t["source"] != "llm":
            t["context"] = None
        elif t["agent"] == "Analyst":
            t["context"] = _prompt_for(gateway.records, "Analyst", "headline", t["headline"])
        else:
            t["context"] = _prompt_for(gateway.records, "Storyteller", "text", t.get("body", t["text"]))
    texts = [t for t in texts if t["context"]]
    return texts + corrupted_controls(texts)


def corrupted_controls(texts: list[dict]) -> list[dict]:
    """Deliberately wrong versions of three cards: the judge must score them low (sanity check)."""
    controls = []
    goals = [t for t in texts if t["kind"] == "moment card" and "goal" in t["moment"]][:3]
    for t in goals:
        wrong = (t["text"].replace("Emberfield", "@@").replace("Saltmarsh Comets", "Emberfield")
                 .replace("@@", "Saltmarsh Comets") + " It was his 7th goal of the night.")
        controls.append({**t, "kind": "control (corrupted)", "text": wrong})
    return controls


def main() -> None:
    load_dotenv(ROOT / ".env")
    endpoint = os.environ["FOUNDRY_ENDPOINT"].split("/openai")[0]
    model_config = {"azure_endpoint": endpoint, "api_key": os.environ["FOUNDRY_API_KEY"],
                    "azure_deployment": os.getenv("FOUNDRY_MODEL", "gpt-4.1-mini"), "api_version": "2024-10-21"}
    evaluators = {"groundedness": GroundednessEvaluator(model_config),
                  "coherence": CoherenceEvaluator(model_config),
                  "fluency": FluencyEvaluator(model_config)}
    texts = asyncio.run(collect())
    print(f"Evaluating {len(texts)} verified texts with Foundry evaluators…")
    for t in texts:
        query = QUERIES[t["agent"]]
        for name, evaluator in evaluators.items():
            kwargs = {"response": t["text"]}
            if name == "groundedness":
                kwargs |= {"context": t["context"], "query": query}
            elif name == "coherence":
                kwargs |= {"query": query}
            for attempt in range(4):
                try:
                    t[name] = evaluator(**kwargs)[name]
                    break
                except Exception as exc:  # rate limit (30k TPM deployment): back off and retry
                    if attempt == 3:
                        raise
                    print(f"  retry {name}: {type(exc).__name__}")
                    time.sleep(20)
            time.sleep(1.5)
        label = t.get("fan") or t.get("moment")
        print(f"  {t['kind']:20s} {label:18s} G {t['groundedness']} C {t['coherence']} F {t['fluency']}")

    rows = []
    for kind in ("moment card", "catch-up", "full-time recap", "control (corrupted)"):
        group = [t for t in texts if t["kind"] == kind]
        if group:
            rows.append({"kind": kind, "n": len(group), **{
                m: round(statistics.mean(t[m] for t in group), 2) for m in ("groundedness", "coherence", "fluency")}})
    real = [t for t in texts if t["kind"] != "control (corrupted)"]
    metrics = ("groundedness", "coherence", "fluency")
    overall = {m: round(statistics.mean(t[m] for t in real), 2) for m in metrics}
    passing = {m: round(sum(t[m] >= 3 for t in real) / len(real), 2) for m in metrics}
    report = {"judge": model_config["azure_deployment"], "texts": len(real), "by_kind": rows, "overall": overall,
              "pass_rate_at_3": passing, "items": [{k: v for k, v in t.items() if k != "context"} for t in texts]}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("\n| Texts | n | Groundedness | Coherence | Fluency |\n|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['kind']} | {r['n']} | {r['groundedness']} | {r['coherence']} | {r['fluency']} |")
    print(f"| **all shown to fans** | {len(real)} | **{overall['groundedness']}** | **{overall['coherence']}** "
          f"| **{overall['fluency']}** |")
    print(f"\nShare scoring ≥ 3/5: {passing}  →  {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
