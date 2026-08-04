"""Runtime enforcement of a graph's declared caps.

Search will propose degenerate topologies -- infinite critic/worker ping-pong,
fan-outs of forty workers -- and the engine must survive them cheaply. Every
limit is checked before admitting new work, so an over-budget rollout is
truncated and scored rather than allowed to run away.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from aas.core.graph.schema import GraphBudget

from .trace import FailureSignal, TokenUsage


@dataclass(slots=True)
class BudgetTracker:
    budget: GraphBudget
    started_at: float = field(default_factory=time.monotonic)
    steps: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.budget.max_wall_clock_s - self.elapsed_s)

    def charge(self, usage: TokenUsage) -> None:
        self.usage = self.usage + usage

    def spend_step(self) -> None:
        self.steps += 1

    def exceeded(self) -> FailureSignal | None:
        """First violated limit, or None. Checked before scheduling each round."""
        if self.steps >= self.budget.max_steps:
            return FailureSignal.STEP_BUDGET_EXHAUSTED
        if self.usage.total_tokens >= self.budget.max_total_tokens:
            return FailureSignal.TOKEN_BUDGET_EXHAUSTED
        if self.elapsed_s >= self.budget.max_wall_clock_s:
            return FailureSignal.WALL_CLOCK_EXHAUSTED
        if self.budget.max_usd is not None and self.usage.usd >= self.budget.max_usd:
            return FailureSignal.COST_BUDGET_EXHAUSTED
        return None

    def steps_remaining(self) -> int:
        return max(0, self.budget.max_steps - self.steps)
