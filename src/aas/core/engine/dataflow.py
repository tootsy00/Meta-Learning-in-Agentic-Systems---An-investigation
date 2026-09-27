"""Reference execution backend: a round-based (bulk-synchronous) dataflow scheduler.

Why a scheduler of our own rather than LangGraph/AutoGen directly: the search
loop needs three things those runtimes do not give cheaply -- a candidate that is
pure serializable data, a trace detailed enough to mutate against, and hard
budget truncation on adversarial topologies. `GraphExecutor` stays a protocol so
a LangGraph backend can be added as a compilation target later; this module is
the semantics reference those backends must match.

Execution model, one round at a time:

1. Select every node whose inbox satisfies its join policy.
2. Run them concurrently (each expanded into `fanout` replicas).
3. Evaluate each outbound edge's condition, transform the payload, deliver.
4. Repeat until nothing is runnable or a budget is hit.

Rounds make parallelism explicit and traces deterministic in ordering, which
matters when the reflection step reads them. If a round finds nothing runnable
while activations are still pending -- an `ALL` join waiting on a branch that got
pruned -- the join is relaxed once and the event is recorded, so a candidate
never deadlocks silently.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict

from aas.core.graph.schema import (
    AgentEdge,
    AgentNode,
    ContentTransform,
    JoinPolicy,
    TopologyGraph,
)

from .budget import BudgetTracker
from .prompts import DefaultPromptCompiler
from .protocols import (
    ModelClient,
    NodeContext,
    NodeOutput,
    NodeRunner,
    PredicateRegistry,
    ToolRegistry,
)
from .trace import (
    Activation,
    FailureSignal,
    LLMRequest,
    Message,
    NodeInvocation,
    RolloutResult,
    RolloutStatus,
    RolloutTrace,
    TaskInstance,
    TokenUsage,
    TraceEvent,
)


class ExecutionConfigError(RuntimeError):
    """A graph references something the runtime cannot resolve.

    Raised rather than swallowed: a candidate naming an unregistered predicate is
    outside the declared search space, and hiding that would let the optimizer
    score a graph whose routing silently never fires.
    """


class LLMNodeRunner:
    """Default runner: compile a prompt, make one completion call.

    Tool execution and ReAct cycles are intentionally absent -- they belong to a
    dedicated runner so that the scheduler and this baseline stay small.
    """

    def __init__(self, compiler: DefaultPromptCompiler) -> None:
        self._compiler = compiler

    async def run(self, ctx: NodeContext) -> NodeOutput:
        node = ctx.node
        messages, truncated = self._compiler.compile(node, ctx.inbox, ctx.task.input)
        request = LLMRequest(
            model_id=node.model_id,
            messages=messages,
            temperature=node.temperature,
            max_output_tokens=node.max_output_tokens,
            tools=node.tool_access,
            metadata={
                "node_id": node.id,
                "visit": ctx.visit,
                "replica": ctx.replica,
                "task_id": ctx.task.id,
            },
        )
        try:
            response = await asyncio.wait_for(
                ctx.model_client.complete(request), timeout=node.timeout_s
            )
        except TimeoutError:
            return NodeOutput(content="", prompt=messages, truncated=truncated, error="timeout")
        except Exception as exc:  # provider errors must not abort the whole rollout
            return NodeOutput(
                content="", prompt=messages, truncated=truncated, error=repr(exc)
            )
        return NodeOutput(
            content=response.text,
            prompt=messages,
            usage=response.usage,
            truncated=truncated,
        )


class DataflowExecutor:
    """Runs one `TopologyGraph` against one `TaskInstance`."""

    def __init__(
        self,
        model_client: ModelClient,
        *,
        tools: ToolRegistry | None = None,
        predicates: PredicateRegistry | None = None,
        runner: NodeRunner | None = None,
    ) -> None:
        self._client = model_client
        self._tools = tools
        self._predicates = predicates
        self._runner = runner or LLMNodeRunner(DefaultPromptCompiler(model_client.count_tokens))

    async def rollout(self, graph: TopologyGraph, task: TaskInstance) -> RolloutResult:
        trace = RolloutTrace(
            graph_id=graph.id,
            graph_semantic_hash=graph.semantic_hash,
            task_id=task.id,
        )
        tracker = BudgetTracker(graph.budget)
        semaphore = asyncio.Semaphore(graph.budget.max_concurrency)
        started = time.monotonic()

        pending: dict[str, list[Activation]] = defaultdict(list)
        for entry in graph.entry:
            pending[entry].append(Activation(content=task.input, label="task"))

        visits: dict[str, int] = defaultdict(int)
        latest_output: dict[str, str] = {}
        status = RolloutStatus.COMPLETED
        round_index = 0

        while True:
            exceeded = tracker.exceeded()
            if exceeded is not None:
                trace.add_signal(exceeded)
                status = RolloutStatus.BUDGET_EXHAUSTED
                self._event(trace, "budget_exhausted", exceeded.value)
                break

            ready = self._select_ready(graph, pending, visits, trace, relaxed=False)
            if not ready:
                ready = self._select_ready(graph, pending, visits, trace, relaxed=True)
                if ready:
                    trace.add_signal(FailureSignal.JOIN_RELAXED)
                    self._event(
                        trace,
                        "join_relaxed",
                        "no join was satisfiable; firing nodes on partial input",
                        {"nodes": ready},
                    )
            if not ready:
                break

            invocations = await self._run_round(
                graph, task, ready, pending, visits, tracker, semaphore, round_index, trace
            )
            for invocation in invocations:
                trace.invocations.append(invocation)
                if invocation.node_id in graph.outputs and invocation.output:
                    latest_output[invocation.node_id] = invocation.output

            await self._route(graph, invocations, pending, trace)
            round_index += 1

        output = "\n\n".join(latest_output[n] for n in graph.outputs if n in latest_output)
        if not output:
            trace.add_signal(FailureSignal.NO_OUTPUT_PRODUCED)
            if status is RolloutStatus.COMPLETED:
                status = RolloutStatus.NO_OUTPUT

        self._flag_dead_branches(graph, trace)

        return RolloutResult(
            task_id=task.id,
            output=output,
            status=status,
            usage=tracker.usage,
            latency_s=time.monotonic() - started,
            trace=trace,
        )

    # -- scheduling ------------------------------------------------------

    def _select_ready(
        self,
        graph: TopologyGraph,
        pending: dict[str, list[Activation]],
        visits: dict[str, int],
        trace: RolloutTrace,
        *,
        relaxed: bool,
    ) -> list[str]:
        ready: list[str] = []
        for node in graph.nodes:
            inbox = pending.get(node.id) or []
            if not inbox:
                continue
            if visits[node.id] >= node.max_visits:
                # Drop the payload: keeping it would stall the loop forever.
                pending.pop(node.id, None)
                trace.add_signal(FailureSignal.VISIT_CAP_HIT)
                self._event(
                    trace,
                    "visit_cap_hit",
                    f"node {node.id!r} reached max_visits={node.max_visits}; input discarded",
                    {"node_id": node.id},
                )
                continue
            if relaxed or self._join_satisfied(graph, node, inbox):
                ready.append(node.id)
        return ready

    def _join_satisfied(
        self, graph: TopologyGraph, node: AgentNode, inbox: list[Activation]
    ) -> bool:
        # A seeded task activation always fires an entry node, even if it also has
        # inbound edges from a loop.
        if any(a.edge_key is None for a in inbox):
            return True
        distinct = {a.edge_key for a in inbox}
        if node.join is JoinPolicy.ANY:
            return len(distinct) >= 1
        if node.join is JoinPolicy.K_OF_N:
            return len(distinct) >= (node.join_k or 1)
        return len(distinct) >= len(graph.inbound(node.id))

    async def _run_round(
        self,
        graph: TopologyGraph,
        task: TaskInstance,
        ready: list[str],
        pending: dict[str, list[Activation]],
        visits: dict[str, int],
        tracker: BudgetTracker,
        semaphore: asyncio.Semaphore,
        round_index: int,
        trace: RolloutTrace,
    ) -> list[NodeInvocation]:
        planned: list[tuple[AgentNode, list[Activation], int, int]] = []
        for node_id in ready:
            if len(planned) >= tracker.steps_remaining():
                trace.add_signal(FailureSignal.STEP_BUDGET_EXHAUSTED)
                break
            node = graph.node(node_id)
            inbox = pending.pop(node_id, [])
            visits[node_id] += 1
            for replica in range(node.fanout):
                if len(planned) >= tracker.steps_remaining():
                    trace.add_signal(FailureSignal.STEP_BUDGET_EXHAUSTED)
                    break
                planned.append((node, inbox, visits[node_id], replica))

        async def execute(
            node: AgentNode, inbox: list[Activation], visit: int, replica: int
        ) -> NodeInvocation:
            ctx = NodeContext(
                graph=graph,
                node=node,
                task=task,
                inbox=inbox,
                visit=visit,
                replica=replica,
                round_index=round_index,
                model_client=self._client,
                tools=self._tools,
                budget=tracker,
            )
            started = time.monotonic()
            async with semaphore:
                output = await self._runner.run(ctx)
            invocation = NodeInvocation(
                node_id=node.id,
                round_index=round_index,
                visit=visit,
                replica=replica,
                inputs=inbox,
                prompt=output.prompt,
                output=output.content,
                usage=output.usage,
                tool_results=output.tool_results,
                started_at=started,
                duration_s=time.monotonic() - started,
                error=output.error,
            )
            if output.truncated:
                trace.add_signal(FailureSignal.CONTEXT_TRUNCATED)
            if output.error == "timeout":
                trace.add_signal(FailureSignal.NODE_TIMEOUT)
            elif output.error:
                trace.add_signal(FailureSignal.NODE_ERROR)
            return invocation

        invocations = await asyncio.gather(*(execute(*plan) for plan in planned))
        for invocation in invocations:
            tracker.spend_step()
            tracker.charge(invocation.usage)
        return list(invocations)

    # -- routing ---------------------------------------------------------

    async def _route(
        self,
        graph: TopologyGraph,
        invocations: list[NodeInvocation],
        pending: dict[str, list[Activation]],
        trace: RolloutTrace,
    ) -> None:
        for invocation in invocations:
            if invocation.error or not invocation.output:
                continue
            for edge in graph.outbound(invocation.node_id):
                if not await self._condition_holds(graph, edge, invocation.output):
                    invocation.blocked_edges.append(edge.key)
                    continue
                source = graph.node(edge.source)
                payload = self._transform(edge.transform, invocation.output, source)
                pending[edge.target].append(
                    Activation(
                        content=payload,
                        source_node=edge.source,
                        label=edge.label,
                        edge_key=edge.key,
                    )
                )
                invocation.routed_edges.append(edge.key)

    async def _condition_holds(self, graph: TopologyGraph, edge: AgentEdge, payload: str) -> bool:
        condition = edge.condition
        if condition.kind == "always":
            return True
        if condition.kind == "predicate":
            if self._predicates is None:
                raise ExecutionConfigError(
                    f"edge {edge.key} uses predicate {condition.name!r} but no "
                    "PredicateRegistry was supplied"
                )
            result = await self._predicates.evaluate(condition.name, condition.args, payload)
            return result != condition.negate
        source = graph.node(edge.source)
        response = await self._client.complete(
            LLMRequest(
                model_id=condition.model_id or source.model_id,
                messages=[
                    Message(
                        role="system",
                        content="Answer with exactly YES or NO.",
                    ),
                    Message(
                        role="user",
                        content=f"{condition.question}\n\n---\n{payload}",
                    ),
                ],
                temperature=0.0,
                max_output_tokens=4,
                metadata={"router_edge": edge.key},
            )
        )
        return response.text.strip().upper().startswith("YES")

    def _transform(self, transform: ContentTransform, output: str, source: AgentNode) -> str:
        """Shape the payload travelling down an edge.

        `summary` currently head-truncates rather than calling a model; a
        model-backed summarizer is a drop-in replacement once its cost is part of
        the objective.
        """
        text = output
        if transform.kind == "field":
            text = _extract_field(output, transform.field or "")
        if transform.max_tokens is not None:
            budget = transform.max_tokens
            while text and self._client.count_tokens(text, source.model_id) > budget:
                text = text[: int(len(text) * 0.9)]
        elif transform.kind == "summary":
            text = text[:2000]
        return text

    # -- diagnostics -----------------------------------------------------

    def _flag_dead_branches(self, graph: TopologyGraph, trace: RolloutTrace) -> None:
        executed = {i.node_id for i in trace.invocations}
        idle = sorted({n.id for n in graph.nodes} - executed)
        if idle:
            trace.add_signal(FailureSignal.DEAD_BRANCH)
            self._event(
                trace, "dead_branch", "node(s) never executed in this rollout", {"nodes": idle}
            )

    def _event(
        self, trace: RolloutTrace, kind: str, message: str, data: dict | None = None
    ) -> None:
        trace.events.append(
            TraceEvent(at=time.monotonic(), kind=kind, message=message, data=data or {})
        )


def _extract_field(output: str, path: str) -> str:
    """Best-effort dotted-path lookup into a JSON payload; falls back to raw text."""
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return output
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return output
    return value if isinstance(value, str) else json.dumps(value)


__all__ = [
    "DataflowExecutor",
    "ExecutionConfigError",
    "LLMNodeRunner",
    "TokenUsage",
]
