"""Deterministic in-process doubles.

Used by the tests and by examples so that topology semantics can be exercised
without a provider key. They also define the surface a real LiteLLM-backed client
has to implement.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .trace import LLMRequest, LLMResponse, TokenUsage, ToolResult


class ScriptedModelClient:
    """Returns canned text keyed by node id, with usage accounted approximately."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        *,
        default: str | Callable[[LLMRequest], str] = "ok",
        usd_per_1k_tokens: float = 0.001,
    ) -> None:
        self._responses = responses or {}
        self._default = default
        self._rate = usd_per_1k_tokens
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        node_id = request.metadata.get("node_id")
        if node_id in self._responses:
            text = self._responses[node_id]
        elif callable(self._default):
            text = self._default(request)
        else:
            text = self._default

        prompt_tokens = sum(
            self.count_tokens(m.content, request.model_id) for m in request.messages
        )
        completion_tokens = self.count_tokens(text, request.model_id)
        total = prompt_tokens + completion_tokens
        return LLMResponse(
            text=text,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usd=total / 1000 * self._rate,
            ),
        )

    def count_tokens(self, text: str, model_id: str) -> int:
        return max(1, len(text) // 4)


class DictPredicateRegistry:
    """Named routing predicates over an edge payload."""

    def __init__(self, predicates: dict[str, Callable[[dict[str, Any], str], bool]]) -> None:
        self._predicates = predicates

    async def evaluate(self, name: str, arguments: dict[str, Any], payload: str) -> bool:
        if name not in self._predicates:
            raise KeyError(f"unknown predicate {name!r}")
        return bool(self._predicates[name](arguments, payload))


class DictToolRegistry:
    def __init__(self, tools: dict[str, Callable[[dict[str, Any]], str]]) -> None:
        self._tools = tools

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in self._tools:
            return ToolResult(name=name, content="", error=f"unknown tool {name!r}")
        return ToolResult(name=name, content=self._tools[name](arguments))
