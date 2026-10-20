"""Load test: N viewers watching at the same time, each with their own replay session.

Opens N Server-Sent Event streams (speed ×40) against a running server, and meanwhile
probes the API every half second. Reports events received per viewer and the probe
latency (p50/p95), so we know the public demo stays responsive with several judges.

Usage:
    python -m comeback --port 8000 &          # or the public URL
    python scripts/load_test.py --viewers 10 --seconds 30 [--url http://localhost:8000]
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx


async def viewer(client: httpx.AsyncClient, url: str, seconds: float) -> dict:
    session = f"load-{uuid.uuid4().hex[:8]}"
    counts = {"event": 0, "snapshot": 0, "crowd": 0, "card": 0}
    first = None
    start = time.perf_counter()
    try:
        async with client.stream("GET", f"{url}/api/stream?session={session}&speed=40", timeout=None) as response:
            kind = None
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: ") and kind:
                    if kind == "state" and first is None:
                        first = time.perf_counter() - start
                    if kind in counts:
                        counts[kind] += 1
                if time.perf_counter() - start > seconds:
                    break
    except httpx.HTTPError as exc:
        return {"error": str(exc)}
    return {"first_state_s": first, **counts}


async def probe(client: httpx.AsyncClient, url: str, seconds: float) -> list[float]:
    latencies = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        start = time.perf_counter()
        response = await client.get(f"{url}/api/profiles")
        response.raise_for_status()
        latencies.append((time.perf_counter() - start) * 1000)
        await asyncio.sleep(0.5)
    return latencies


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--viewers", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    async with httpx.AsyncClient(timeout=30) as client:
        results, latencies = await asyncio.gather(
            asyncio.gather(*(viewer(client, args.url, args.seconds) for _ in range(args.viewers))),
            probe(client, args.url, args.seconds))
    ok = [r for r in results if "error" not in r]
    rate = [r["event"] / args.seconds for r in ok]
    latencies.sort()
    report = {
        "viewers": args.viewers, "seconds": args.seconds, "ok": len(ok), "errors": len(results) - len(ok),
        "events_per_viewer_per_s": {"min": min(rate), "median": statistics.median(rate)} if rate else None,
        "first_state_s_max": max(r["first_state_s"] for r in ok) if ok else None,
        "api_latency_ms": {"p50": latencies[len(latencies) // 2], "p95": latencies[int(len(latencies) * 0.95)]},
    }
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
