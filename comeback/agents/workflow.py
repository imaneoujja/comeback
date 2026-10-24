"""Verified-writing workflow (Microsoft Agent Framework).

    WriteRequest ──► [Writer agent] ──Draft──► [Verifier] ──ok──► output (source "llm")
         ▲                │                        │
         │           LLM unavailable          rejected, attempts left
         │                ▼                        │
         │           [Fallback] ◄──gave up─────────┤
         │                │                        │
         │                └──► output (source "template")
         └──────────── feedback ◄──────────────────┘

The same workflow serves the Analyst (moment cards) and the Storyteller
(personalised catch-ups): nothing reaches a fan without passing the Verifier,
and every failure path ends with a usable, fact-based template.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from comeback.agents.llm import LLMGateway, LLMUnavailable

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # first draft + 2 retries

Tracer = Callable[[dict[str, Any]], None]  # receives one step of the agents' work, for live display


def _no_trace(_: dict[str, Any]) -> None:
    return None


class VerifiedWriter(Protocol):
    """A writing agent whose output the Verifier can check and a template can replace."""

    agent_name: str
    instructions: str

    def label(self, task: Any) -> str: ...

    def prompt(self, task: Any, feedback: list[str]) -> str: ...

    def parse(self, text: str) -> dict[str, Any]: ...

    def verify(self, task: Any, output: dict[str, Any]) -> list[str]: ...

    def fallback(self, task: Any) -> dict[str, Any]: ...


@dataclass
class WriteRequest:
    task: Any
    attempt: int = 1
    feedback: list[str] = field(default_factory=list)
    history: list[list[str]] = field(default_factory=list)


@dataclass
class Draft:
    request: WriteRequest
    output: dict[str, Any] | None
    error: str | None = None


@dataclass
class FallbackRequest:
    request: WriteRequest
    reason: str


@dataclass
class WrittenResult:
    """Final output of the workflow, with its provenance."""

    output: dict[str, Any]
    source: str  # "llm" | "template"
    verified: bool
    attempts: int
    rejections: list[list[str]]
    fallback_reason: str | None = None


class WriterExecutor(Executor):
    """Runs the writing agent (Analyst or Storyteller) through the LLM gateway."""

    def __init__(self, writer: VerifiedWriter, gateway: LLMGateway, trace: Tracer) -> None:
        super().__init__(id=writer.agent_name)
        self.writer, self.gateway, self.trace = writer, gateway, trace

    @handler
    async def write(self, request: WriteRequest, ctx: WorkflowContext[Draft | FallbackRequest]) -> None:
        label = self.writer.label(request.task)
        prompt = self.writer.prompt(request.task, request.feedback)
        try:
            reply = await self.gateway.ask(self.writer.agent_name, self.writer.instructions, prompt)
        except LLMUnavailable as exc:
            self.trace({"agent": self.writer.agent_name, "step": "unavailable", "label": label, "detail": str(exc)})
            await ctx.send_message(FallbackRequest(request, f"LLM unavailable: {exc}"))
            return
        try:
            output = self.writer.parse(reply.text)
        except (ValueError, KeyError, TypeError) as exc:
            self.trace({"agent": self.writer.agent_name, "step": "draft", "label": label, "attempt": request.attempt,
                        "detail": "(invalid JSON)", "cached": reply.cached})
            await ctx.send_message(Draft(request, None, f"Reply was not valid JSON with the expected keys ({exc})."))
            return
        preview = output.get("headline") or output.get("text", "")
        self.trace({"agent": self.writer.agent_name, "step": "draft", "label": label, "attempt": request.attempt,
                    "detail": preview, "cached": reply.cached})
        await ctx.send_message(Draft(request, output))


class VerifierExecutor(Executor):
    """Checks a draft against the facts; asks for a revision or gives up to the fallback."""

    def __init__(self, writer: VerifiedWriter, trace: Tracer) -> None:
        super().__init__(id="Verifier")
        self.writer, self.trace = writer, trace

    @handler
    async def check(self, draft: Draft,
                    ctx: WorkflowContext[WriteRequest | FallbackRequest, WrittenResult]) -> None:
        request = draft.request
        issues = [draft.error] if draft.error else self.writer.verify(request.task, draft.output or {})
        step = {"agent": "Verifier", "step": "rejected" if issues else "verified", "writer": self.writer.agent_name,
                "label": self.writer.label(request.task), "attempt": request.attempt,
                "detail": issues[0] if issues else self.writer.agent_name}
        if issues and draft.output:  # the rejected text itself, for the live fact-check display
            parts = ("headline", "why_it_matters", "text")
            step["draft"] = " ".join(str(draft.output[k]) for k in parts if draft.output.get(k))
        self.trace(step)
        if not issues:
            await ctx.yield_output(WrittenResult(draft.output or {}, "llm", True, request.attempt, request.history))
            return
        history = [*request.history, issues]
        if request.attempt < MAX_ATTEMPTS:
            await ctx.send_message(WriteRequest(request.task, request.attempt + 1, issues, history))
        else:
            await ctx.send_message(FallbackRequest(
                WriteRequest(request.task, request.attempt, issues, history),
                f"Verifier rejected {request.attempt} drafts"))


class FallbackExecutor(Executor):
    """Builds a deterministic, fact-based template output."""

    def __init__(self, writer: VerifiedWriter, trace: Tracer) -> None:
        super().__init__(id="TemplateFallback")
        self.writer, self.trace = writer, trace

    @handler
    async def fallback(self, request: FallbackRequest, ctx: WorkflowContext[Any, WrittenResult]) -> None:
        log.info("%s fell back to template: %s", self.writer.agent_name, request.reason)
        self.trace({"agent": "Fallback", "step": "template", "label": self.writer.label(request.request.task),
                    "detail": request.reason, "writer": self.writer.agent_name})
        await ctx.yield_output(WrittenResult(
            self.writer.fallback(request.request.task), "template", True,
            request.request.attempt, request.request.history, request.reason))


def build_workflow(writer: VerifiedWriter, gateway: LLMGateway, trace: Tracer = _no_trace):
    """Wire Writer → Verifier (→ Writer retry) → Fallback as an Agent Framework workflow."""
    write = WriterExecutor(writer, gateway, trace)
    verify = VerifierExecutor(writer, trace)
    fallback = FallbackExecutor(writer, trace)
    return (
        WorkflowBuilder(start_executor=write, name=f"{writer.agent_name}VerifiedWriting")
        .add_edge(write, verify, condition=lambda m: isinstance(m, Draft))
        .add_edge(write, fallback, condition=lambda m: isinstance(m, FallbackRequest))
        .add_edge(verify, write, condition=lambda m: isinstance(m, WriteRequest))
        .add_edge(verify, fallback, condition=lambda m: isinstance(m, FallbackRequest))
        .build()
    )


async def run_verified(writer: VerifiedWriter, task: Any, gateway: LLMGateway,
                       trace: Tracer | None = None) -> WrittenResult:
    """Run the verified-writing workflow for one task; ``trace`` receives each step (draft, rejection…)."""
    result = await build_workflow(writer, gateway, trace or _no_trace).run(WriteRequest(task))
    outputs = result.get_outputs()
    if not outputs:  # defensive: the workflow always yields, but never leave a fan without text
        return WrittenResult(writer.fallback(task), "template", True, 0, [], "workflow produced no output")
    return outputs[0]
