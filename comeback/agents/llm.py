"""LLM gateway: Microsoft Agent Framework agents on a Microsoft Foundry deployment.

Everything LLM-related goes through this module so that API changes touch one file.
It adds what a free/limited deployment needs, and what makes the system robust:

* ``LLM_MODE``: ``offline`` (cache only, default: tests and judges need no key),
  ``live`` (call Foundry), ``record`` (live + append to the committed cache).
* a response cache keyed by hash(agent, model, instructions, prompt),
* a rate limiter (requests per minute) and a daily call budget persisted to disk,
* a timeout; any failure raises :class:`LLMUnavailable` so callers fall back to templates.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "data" / "llm_cache.jsonl"
DEFAULT_BUDGET = ROOT / "data" / "llm_budget.json"


class LLMMode(str, Enum):
    """How the gateway may reach the model."""

    OFFLINE = "offline"
    LIVE = "live"
    RECORD = "record"


class LLMUnavailable(Exception):
    """The model could not (or must not) be called; use a fallback."""


@dataclass(frozen=True)
class LLMSettings:
    """Gateway configuration, usually read from the environment / ``.env``."""

    mode: LLMMode = LLMMode.OFFLINE
    endpoint: str = ""
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    cache_path: Path = DEFAULT_CACHE
    budget_path: Path = DEFAULT_BUDGET
    requests_per_minute: int = 10
    daily_limit: int = 300
    timeout_s: float = 30.0
    temperature: float = 0.4

    @classmethod
    def from_env(cls) -> "LLMSettings":
        load_dotenv(ROOT / ".env")
        return cls(
            mode=LLMMode(os.getenv("LLM_MODE", "offline").lower()),
            endpoint=os.getenv("FOUNDRY_ENDPOINT", ""),
            api_key=os.getenv("FOUNDRY_API_KEY", ""),
            model=os.getenv("FOUNDRY_MODEL", "gpt-4.1-mini"),
            daily_limit=int(os.getenv("LLM_DAILY_LIMIT", "300")),
        )


def foundry_base_url(endpoint: str) -> str:
    """Normalise a Foundry endpoint to its OpenAI-compatible v1 base URL."""
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/openai/v1"):
        endpoint += "/openai/v1"
    return endpoint + "/"


class LLMCache:
    """Append-only JSONL cache of model replies."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, str] = {}
        self.used: set[str] = set()
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        self._data[record["key"]] = record["text"]

    def get(self, key: str) -> str | None:
        if key in self._data:
            self.used.add(key)
        return self._data.get(key)

    def compact(self) -> int:
        """Rewrite the file keeping only the replies used in this run; returns how many were dropped."""
        with self.path.open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        kept = {r["key"]: r for r in records if r["key"] in self.used}
        with self.path.open("w", encoding="utf-8") as f:
            for record in kept.values():
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return len(records) - len(kept)

    def put(self, key: str, text: str, meta: dict[str, Any], persist: bool) -> None:
        self._data[key] = text
        self.used.add(key)
        if persist:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, **meta, "text": text}, ensure_ascii=False) + "\n")


class RateLimiter:
    """At most ``per_minute`` acquisitions in any 60-second window."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._times and now - self._times[0] >= 60:
                    self._times.popleft()
                if len(self._times) < self.per_minute:
                    self._times.append(now)
                    return
                await asyncio.sleep(60 - (now - self._times[0]) + 0.05)


class DailyBudget:
    """Daily call counter persisted to disk (protects the Azure credit)."""

    def __init__(self, path: Path, limit: int) -> None:
        self.path, self.limit = path, limit

    def _load(self) -> dict[str, Any]:
        today = date.today().isoformat()
        if self.path.exists():
            data = json.loads(self.path.read_text())
            if data.get("date") == today:
                return data
        return {"date": today, "calls": 0}

    def try_spend(self) -> bool:
        data = self._load()
        if data["calls"] >= self.limit:
            return False
        data["calls"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))
        return True

    def used_today(self) -> int:
        return self._load()["calls"]


@dataclass
class LLMReply:
    """A model reply and where it came from."""

    text: str
    cached: bool


@dataclass
class LLMGateway:
    """Creates Agent Framework agents on Foundry and runs them through cache, limiter and budget."""

    settings: LLMSettings = field(default_factory=LLMSettings.from_env)
    stats: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        self.cache = LLMCache(self.settings.cache_path)
        self.limiter = RateLimiter(self.settings.requests_per_minute)
        self.budget = DailyBudget(self.settings.budget_path, self.settings.daily_limit)
        self._client: Any = None
        self._agents: dict[tuple[str, str], Any] = {}

    def cache_key(self, agent_name: str, instructions: str, prompt: str) -> str:
        payload = json.dumps([agent_name, self.settings.model, instructions, prompt], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _agent(self, name: str, instructions: str) -> Any:
        """Lazily build one Agent Framework agent per (name, instructions)."""
        if self._client is None:
            from agent_framework.openai import OpenAIChatCompletionClient

            if not (self.settings.endpoint and self.settings.api_key):
                raise LLMUnavailable("FOUNDRY_ENDPOINT / FOUNDRY_API_KEY not set")
            # Foundry's v1 endpoint is OpenAI-compatible; the model id is the deployment name.
            self._client = OpenAIChatCompletionClient(
                model=self.settings.model,
                base_url=foundry_base_url(self.settings.endpoint),
                api_key=self.settings.api_key,
            )
        key = (name, instructions)
        if key not in self._agents:
            from agent_framework import Agent

            self._agents[key] = Agent(
                client=self._client, name=name, instructions=instructions,
                default_options={"temperature": self.settings.temperature},
            )
        return self._agents[key]

    async def ask(self, agent_name: str, instructions: str, prompt: str) -> LLMReply:
        """Return the agent's reply, from cache when possible. Raises :class:`LLMUnavailable`."""
        key = self.cache_key(agent_name, instructions, prompt)
        cached = self.cache.get(key)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return LLMReply(cached, cached=True)
        if self.settings.mode is LLMMode.OFFLINE:
            self.stats["offline_misses"] += 1
            raise LLMUnavailable("offline mode and no cached reply")
        if not self.budget.try_spend():
            self.stats["budget_exhausted"] += 1
            raise LLMUnavailable(f"daily LLM budget of {self.settings.daily_limit} calls reached")
        await self.limiter.acquire()
        try:
            response = await asyncio.wait_for(
                self._agent(agent_name, instructions).run(prompt), timeout=self.settings.timeout_s)
        except LLMUnavailable:
            raise
        except Exception as exc:  # network, rate limit (429), content filter, timeout...
            self.stats["errors"] += 1
            log.warning("LLM call failed for %s: %s", agent_name, exc)
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        text = (response.text or "").strip()
        if not text:
            self.stats["errors"] += 1
            raise LLMUnavailable("empty reply")
        self.stats["live_calls"] += 1
        self.cache.put(key, text, {"agent": agent_name, "model": self.settings.model},
                       persist=self.settings.mode is LLMMode.RECORD)
        return LLMReply(text, cached=False)


def parse_json_reply(text: str) -> dict[str, Any]:
    """Extract the JSON object from a model reply (tolerates code fences and chatter)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


class SwitchableGateway:
    """One session's view of the shared gateway, with a switch to simulate an LLM outage.

    Used for the failure drill: while ``down`` is set, every agent call fails exactly as a
    real outage would (:class:`LLMUnavailable`), so the workflow's fallback path is exercised live.
    """

    def __init__(self, inner: LLMGateway) -> None:
        self.inner = inner
        self.down = False

    async def ask(self, agent_name: str, instructions: str, prompt: str) -> LLMReply:
        if self.down:
            raise LLMUnavailable("simulated outage (failure drill)")
        return await self.inner.ask(agent_name, instructions, prompt)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class PrecomputedOnlyGateway:
    """A gateway that only serves cached replies, except while recording.

    For texts written per fan *window* (e.g. "what you missed" lines): calling the model for
    any window a fan happens to choose would make the cost grow with the audience, so outside
    ``record`` mode a cache miss raises :class:`LLMUnavailable` and the writer falls back to
    its factual template.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def ask(self, agent_name: str, instructions: str, prompt: str) -> LLMReply:
        if getattr(self.inner, "down", False):
            raise LLMUnavailable("simulated outage (failure drill)")
        if self.inner.settings.mode is not LLMMode.RECORD:
            cached = self.inner.cache.get(self.inner.cache_key(agent_name, instructions, prompt))
            if cached is None:
                raise LLMUnavailable("not a precomputed window: factual template")
            return LLMReply(cached, cached=True)
        return await self.inner.ask(agent_name, instructions, prompt)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
