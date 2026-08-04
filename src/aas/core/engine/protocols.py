"""The contracts every execution backend and provider plugs into.

These exist so that the optimizer never imports a model SDK, and so that the
reference scheduler in `dataflow.py` can be swapped for a LangGraph or AutoGen
backend without touching the search code. A backend is conformant if it accepts
a `TopologyGraph` plus a `TaskInstance` and returns a `RolloutResult` carrying a
full `RolloutTrace`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from aas.core.graph.schema import AgentNode, TopologyGraph

from .budget import BudgetTracker
from .trace import (
    Activation,
    LLMRequest,
    LLMResponse,
    Message,
    RolloutResult,
    TaskInstance,
    TokenUsage,
    ToolResult,
)


@runtime_checkable
class ModelClient(Protocol):
    """Adapter over a completion provider (LiteLLM in production, a stub in tests)."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def count_tokens(self, text: str, model_id: str) -> int:
        """Used to enforce `context_budget` before a request is sent."""
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Resolves the names in `AgentNode.tool_access` to callables."""

    def names(self) -> frozenset[str]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...


@runtime_checkable
class PredicateRegistry(Protocol):
    """Resolves `PredicateCondition.name` for deterministic edge routing."""

    async def evaluate(self, name: str, arguments: dict[str, Any], payload: str) -> bool: ...


@runtime_checkable
class ResponseCache(Protocol):
    """Optional memoization across candidates.

    Sibling candidates in a population usually share most of their nodes, so
    caching on (node identity, resolved prompt) is the single largest cost lever
    in the search loop. Only sound at temperature 0.
    """

    async def get(self, key: str) -> LLMResponse | None: ...

    async def put(self, key: str, response: LLMResponse) -> None: ...


@dataclass(slots=True)
class NodeContext:
    """Everything a node runner is allowed to see.

    A runner gets its inbox and its services and nothing else -- no handle to the
    scheduler. That keeps node execution independently testable and makes it
    impossible for a node to mutate control flow implicitly.
    """

    graph: TopologyGraph
    node: AgentNode
    task: TaskInstance
    inbox: list[Activation]
    visit: int
    replica: int
    round_index: int
    model_client: ModelClient
    tools: ToolRegistry | None = None
    budget: BudgetTracker | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NodeOutput:
    """Result of one node execution, before routing decisions are made."""

    content: str
    prompt: list[Message] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_results: list[ToolResult] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


@runtime_checkable
class NodeRunner(Protocol):
    """How one node turns its inbox into an output.

    Swapping this is how non-LLM nodes (retrievers, code execution, deterministic
    aggregators) enter the search space later without changing the scheduler.
    """

    async def run(self, ctx: NodeContext) -> NodeOutput: ...


@runtime_checkable
class GraphExecutor(Protocol):
    async def rollout(self, graph: TopologyGraph, task: TaskInstance) -> RolloutResult: ...
