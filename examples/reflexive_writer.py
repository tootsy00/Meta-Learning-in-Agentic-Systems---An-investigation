"""A hand-written candidate topology, of the kind the search will later produce.

Run with `python examples/reflexive_writer.py`. It uses the scripted stub client,
so no provider key is needed -- the point is to show the JSON a candidate
serializes to and the trace a rollout produces.

    orchestrator ──► worker_a ─┐
                 └─► worker_b ─┴─► verifier ──(FAIL)──► editor ──┐
                                          └──(PASS)──► publisher │
                                                          ▲      │
                                                          └──────┘
"""

import asyncio

from aas.core.engine import DataflowExecutor, TaskInstance
from aas.core.engine.stub import DictPredicateRegistry, ScriptedModelClient
from aas.core.graph import (
    AgentEdge,
    AgentNode,
    ContentTransform,
    GraphBudget,
    JoinPolicy,
    PredicateCondition,
    PromptStrategy,
    RoleType,
    TopologyGraph,
)


def build() -> TopologyGraph:
    return TopologyGraph(
        name="reflexive_writer",
        nodes=[
            AgentNode(
                id="orchestrator",
                role_type=RoleType.ORCHESTRATOR,
                model_id="openai/gpt-4o",
                prompt_strategy=PromptStrategy.COT,
                instructions="Split the request into two independent sub-questions.",
                temperature=0.3,
            ),
            AgentNode(
                id="worker_a",
                role_type=RoleType.WORKER,
                model_id="anthropic/claude-3-5-sonnet",
                prompt_strategy=PromptStrategy.COT,
            ),
            AgentNode(
                id="worker_b",
                role_type=RoleType.WORKER,
                model_id="meta/llama-3.1-70b",
                prompt_strategy=PromptStrategy.DIRECT,
                temperature=0.7,
            ),
            AgentNode(
                id="verifier",
                role_type=RoleType.VERIFIER,
                model_id="openai/gpt-4o-mini",
                instructions="Reply PASS or FAIL, then one sentence of justification.",
                temperature=0.0,
                context_budget=4000,
            ),
            AgentNode(
                id="editor",
                role_type=RoleType.CRITIC,
                model_id="openai/gpt-4o",
                join=JoinPolicy.ANY,
                max_visits=2,
            ),
            AgentNode(
                id="publisher",
                role_type=RoleType.WORKER,
                model_id="openai/gpt-4o-mini",
                join=JoinPolicy.ANY,
                max_visits=2,
            ),
        ],
        edges=[
            AgentEdge(source="orchestrator", target="worker_a", label="subtask_a"),
            AgentEdge(source="orchestrator", target="worker_b", label="subtask_b"),
            AgentEdge(
                source="worker_a",
                target="verifier",
                label="answer_a",
                transform=ContentTransform(kind="raw", max_tokens=1500),
            ),
            AgentEdge(
                source="worker_b",
                target="verifier",
                label="answer_b",
                transform=ContentTransform(kind="raw", max_tokens=1500),
            ),
            AgentEdge(
                source="verifier",
                target="editor",
                label="rejection",
                condition=PredicateCondition(name="starts_with", args={"prefix": "FAIL"}),
            ),
            AgentEdge(
                source="verifier",
                target="publisher",
                label="approved",
                condition=PredicateCondition(
                    name="starts_with", args={"prefix": "FAIL"}, negate=True
                ),
            ),
            AgentEdge(source="editor", target="publisher", label="revision"),
        ],
        entry=["orchestrator"],
        outputs=["publisher"],
        budget=GraphBudget(max_steps=16, max_total_tokens=60_000, max_concurrency=4),
    )


async def main() -> None:
    graph = build()

    print("=== candidate ===")
    print(f"semantic_hash  {graph.semantic_hash[:16]}")
    print(f"structure_hash {graph.structure_hash[:16]}")
    print(f"diagnostics    {graph.diagnose() or 'healthy'}")

    restored = TopologyGraph.from_json(graph.to_json())
    assert restored.semantic_hash == graph.semantic_hash

    executor = DataflowExecutor(
        ScriptedModelClient(
            {
                "orchestrator": "1. define it  2. give an example",
                "worker_a": "A definition.",
                "worker_b": "An example.",
                "verifier": "FAIL - the example is thin.",
                "editor": "Expand the example with numbers.",
                "publisher": "Final article combining both sub-answers.",
            }
        ),
        predicates=DictPredicateRegistry(
            {"starts_with": lambda args, payload: payload.startswith(args["prefix"])}
        ),
    )
    result = await executor.rollout(
        graph, TaskInstance(id="demo-1", input="Explain gradient descent.")
    )

    print("\n=== rollout ===")
    print(f"status  {result.status}")
    print(f"tokens  {result.usage.total_tokens}  usd {result.usage.usd:.5f}")
    print(f"signals {[s.value for s in result.trace.failure_signals] or 'none'}")
    for inv in result.trace.invocations:
        routed = ", ".join(inv.routed_edges) or "-"
        print(f"  r{inv.round_index} {inv.node_id:<13} -> {routed}")
    print(f"\noutput: {result.output}")


if __name__ == "__main__":
    asyncio.run(main())
