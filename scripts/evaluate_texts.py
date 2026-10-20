"""Evaluate the agents' texts with Microsoft Foundry evaluators (azure-ai-evaluation), before and after the Verifier.

Replays the two playable matches offline (demo + unscripted), records the exact prompt
(the facts) behind every draft, and scores with Foundry's AI-assisted evaluators:
groundedness (against those facts), coherence and fluency, on a 1-5 scale.

* Before the Verifier: the FIRST draft of every text (what a pipeline without the
  Verifier would have shown).
* After the Verifier: the texts fans actually see (verified LLM texts).
* Control: three cards deliberately corrupted (teams swapped, an invented statistic) to
  show the judge is not lenient.

The judge is the project's Foundry deployment (FOUNDRY_* in .env). Identical texts are
scored once.

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
from comeback.fans.profiles import for_match, load_profiles  # noqa: E402

OUT = ROOT / "docs" / "evaluation.json"
MATCHES = [ROOT / "data" / "matches" / "demo-comeback.jsonl", ROOT / "data" / "matches" / "random-3112.jsonl"]
QUERIES = {
    "Analyst": "Write a headline and explain why this football moment matters, using only the given facts.",
    "Storyteller": "Tell this fan what happened while they were away, in their language and from their side.",
}
SCRIPT = [("reda", None, 60.0), ("omar", 63.0, 70.5), ("sofia", 75.5, 86.0)]
FIX = "fix_these_problems_from_your_previous_draft"


class RecordingGateway(LLMGateway):
    """Offline gateway that remembers every (agent, prompt, reply) it serves."""

    def __init__(self) -> None:
        super().__init__(LLMSettings(mode=LLMMode.OFFLINE))
        self.records: list[tuple[str, str, str]] = []

    async def ask(self, agent_name: str, instructions: str, prompt: str) -> LLMReply:
        reply = await super().ask(agent_name, instructions, prompt)
        self.records.append((agent_name, prompt, reply.text))
        return reply


def as_text(agent: str, reply: str) -> str | None:
    try:
        data = parse_json_reply(reply)
    except ValueError:
        return None
    if agent == "Analyst":
        return f"{data.get('headline', '')}\n{data.get('why_it_matters', '')}".strip()
    return f"{data.get('headline', '')}\n{data.get('text', '')}".strip()


async def replay(path: Path, gateway: RecordingGateway) -> list[str]:
    """Replay one match like the demo fans do; return the texts fans are shown (verified LLM texts)."""
    meta, events = load_match(path)
    brain = MatchBrain(meta, gateway)
    profiles = {pid: for_match(p, meta["home"]["id"], meta["away"]["id"]) for pid, p in load_profiles().items()}
    away: dict[str, float] = {}
    shown: list[str] = []
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
                out = await brain.catchup(profiles[fan], start, event["t"], late_join=leave is None)
                if out["source"] == "llm":
                    shown.append(f"{out.get('headline') or ''}\n{out['text']}".strip())
                away[fan] = -1
    for fan in profiles:
        recap = await brain.final_recap(profiles[fan])
        if recap["source"] == "llm":
            shown.append(f"{recap['headline']}\n{recap['text']}".strip())
    shown += [f"{c['headline']}\n{c['why_it_matters']}" for c in brain.cards.values() if c["source"] == "llm"]
    return shown


async def collect() -> list[dict]:
    """First drafts (before the Verifier) and shown texts (after), each with the facts it was written from."""
    gateway = RecordingGateway()
    shown: list[str] = []
    for path in MATCHES:
        shown += await replay(path, gateway)
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for agent, prompt, reply in gateway.records:
        payload = json.loads(prompt)
        payload.pop(FIX, None)                       # retries of the same task share the task's facts
        groups.setdefault(agent + json.dumps(payload, sort_keys=True), []).append((agent, prompt, reply))
    texts = []
    shown_set = set(shown)
    for drafts in groups.values():
        agent, prompt, reply = drafts[0]
        first = as_text(agent, reply)
        if first:
            texts.append({"kind": "before", "agent": agent, "text": first, "context": prompt,
                          "revised": len(drafts) > 1})
        for agent, prompt, reply in drafts:
            text = as_text(agent, reply)
            if text in shown_set:
                texts.append({"kind": "after", "agent": agent, "text": text, "context": prompt})
                break
    cards = [t for t in texts if t["kind"] == "after" and t["agent"] == "Analyst"]
    return texts + corrupted_controls(cards)


def corrupted_controls(texts: list[dict]) -> list[dict]:
    """Deliberately wrong versions of three cards: the judge must score them low (sanity check)."""
    controls = []
    for t in [t for t in texts if "Emberfield" in t["text"] and "Saltmarsh Comets" in t["text"]][:3]:
        wrong = (t["text"].replace("Emberfield", "@@").replace("Saltmarsh Comets", "Emberfield")
                 .replace("@@", "Saltmarsh Comets") + " It was his 7th goal of the night.")
        controls.append({**t, "kind": "control", "text": wrong})
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
    scored: dict[tuple[str, str], dict[str, float]] = {}
    unique = {(t["text"], t["context"]) for t in texts}
    print(f"{len(texts)} texts ({len(unique)} distinct) · judge {model_config['azure_deployment']}")
    for t in texts:
        key = (t["text"], t["context"])
        if key not in scored:
            scored[key] = {}
            query = QUERIES[t["agent"]]
            for name, evaluator in evaluators.items():
                kwargs = {"response": t["text"]}
                if name == "groundedness":
                    kwargs |= {"context": t["context"], "query": query}
                elif name == "coherence":
                    kwargs |= {"query": query}
                for attempt in range(4):
                    try:
                        scored[key][name] = evaluator(**kwargs)[name]
                        break
                    except Exception as exc:  # rate limit (30k TPM deployment): back off and retry
                        if attempt == 3:
                            raise
                        print(f"  retry {name}: {type(exc).__name__}")
                        time.sleep(20)
                time.sleep(1.0)
        t.update(scored[key])
        print(f"  {t['kind']:7s} {t['agent']:11s} G {t['groundedness']} C {t['coherence']} F {t['fluency']}  {t['text'][:60]!r}")

    metrics = ("groundedness", "coherence", "fluency")
    groups = {
        "Before the Verifier: first drafts": [t for t in texts if t["kind"] == "before"],
        "  of which the Verifier sent back": [t for t in texts if t["kind"] == "before" and t["revised"]],
        "After the Verifier: texts shown to fans": [t for t in texts if t["kind"] == "after"],
        "Control: 3 cards deliberately corrupted": [t for t in texts if t["kind"] == "control"],
    }
    rows = [{"set": name, "n": len(group), **{m: round(statistics.mean(t[m] for t in group), 2) for m in metrics},
             "groundedness_below_4": sum(t["groundedness"] < 4 for t in group)}
            for name, group in groups.items() if group]
    report = {"judge": model_config["azure_deployment"], "matches": [p.stem for p in MATCHES], "rows": rows,
              "items": [{k: v for k, v in t.items() if k != "context"} for t in texts]}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("\n| Texts | n | Groundedness | Coherence | Fluency | Groundedness < 4 |\n|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['set']} | {r['n']} | {r['groundedness']} | {r['coherence']} | {r['fluency']} | {r['groundedness_below_4']} |")
    print(f"\n→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
