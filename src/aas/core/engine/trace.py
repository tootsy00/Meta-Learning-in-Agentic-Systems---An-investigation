"""Data recorded by a rollout.

The trace is not a debugging convenience -- it is the training signal. The
reflective mutator reads it to decide what to change, and the failure
instrumentation of Phase 1 §4 mines it for pathologies (repetition loops,
context bloat, dead branches). So it is a first-class, fully serializable model
rather than log lines.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TaskInstance(BaseModel):
    """One evaluation example.

    `strata` carries the tags used to keep task difficulty from being entangled
    with topology quality when validation sets are sampled.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    input: str
    reference: str | None = None
    strata: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Activation(BaseModel):
    """A payload delivered along an edge (or seeded into an entry node)."""

    model_config = ConfigDict(extra="forbid")

    content: str
    source_node: str | None = None
    label: str | None = None
    edge_key: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            usd=self.usd + other.usd,
        )


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    messages: list[Message]
    temperature: float = 0.2
    max_output_tokens: int = 1024
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    content: str
    error: str | None = None


class NodeInvocation(BaseModel):
    """One execution of one node. Nodes on loops produce several of these."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=lambda: _new_id("inv"))
    node_id: str
    round_index: int
    visit: int = Field(description="1-based count of how many times this node has run.")
    replica: int = Field(default=0, description="Index within a fanout group.")

    inputs: list[Activation] = Field(default_factory=list)
    prompt: list[Message] = Field(default_factory=list)
    output: str = ""
    usage: TokenUsage = Field(default_factory=TokenUsage)
    tool_results: list[ToolResult] = Field(default_factory=list)

    started_at: float = 0.0
    duration_s: float = 0.0
    error: str | None = None

    routed_edges: list[str] = Field(default_factory=list)
    blocked_edges: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    """Engine-level occurrence that is not a node execution."""

    model_config = ConfigDict(extra="forbid")

    at: float
    kind: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class RolloutStatus(StrEnum):
    COMPLETED = "completed"
    NO_OUTPUT = "no_output"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


class FailureSignal(StrEnum):
    """Machine-detectable pathologies attached to a trace.

    The engine emits only what it observes mechanically. Higher-order detectors
    (semantic repetition, unproductive debate) are added by the Phase 1 §4
    instrumentation, which post-processes the same trace.
    """

    STEP_BUDGET_EXHAUSTED = "step_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    WALL_CLOCK_EXHAUSTED = "wall_clock_exhausted"
    COST_BUDGET_EXHAUSTED = "cost_budget_exhausted"
    NODE_TIMEOUT = "node_timeout"
    NODE_ERROR = "node_error"
    CONTEXT_TRUNCATED = "context_truncated"
    JOIN_RELAXED = "join_relaxed"
    VISIT_CAP_HIT = "visit_cap_hit"
    NO_OUTPUT_PRODUCED = "no_output_produced"
    DEAD_BRANCH = "dead_branch"


class RolloutTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rollout_id: str = Field(default_factory=lambda: _new_id("roll"))
    graph_id: str
    graph_semantic_hash: str
    task_id: str

    invocations: list[NodeInvocation] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    failure_signals: list[FailureSignal] = Field(default_factory=list)

    def add_signal(self, signal: FailureSignal) -> None:
        if signal not in self.failure_signals:
            self.failure_signals.append(signal)

    def invocations_of(self, node_id: str) -> list[NodeInvocation]:
        return [i for i in self.invocations if i.node_id == node_id]


class RolloutResult(BaseModel):
    """What the evaluator scores. `output` is the concatenated answer text.

    Deliberately carries no accuracy field: scoring is the evaluator's job, and
    keeping it out means a result can be cached and re-scored under a different
    objective without re-running the graph.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    output: str
    status: RolloutStatus
    usage: TokenUsage
    latency_s: float
    trace: RolloutTrace
