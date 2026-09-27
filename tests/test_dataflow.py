"""Semantics the reference executor guarantees.

These double as the conformance suite any alternative backend (LangGraph,
AutoGen) must satisfy to be interchangeable behind `GraphExecutor`.
"""

from aas.core.engine import DataflowExecutor, FailureSignal, RolloutStatus, TaskInstance
from aas.core.engine.stub import DictPredicateRegistry, ScriptedModelClient
from aas.core.graph import (
    AgentEdge,
    AgentNode,
    ContentTransform,
    GraphBudget,
    JoinPolicy,
    LLMRouterCondition,
    PredicateCondition,
    RoleType,
    TopologyGraph,
)

TASK = TaskInstance(id="t1", input="Summarize the theory of evolution.")


def node(node_id: str, **kwargs) -> AgentNode:
    kwargs.setdefault("role_type", RoleType.WORKER)
    kwargs.setdefault("model_id", "openai/gpt-4o-mini")
    return AgentNode(id=node_id, **kwargs)


def executor(responses=None, predicates=None, **kwargs) -> DataflowExecutor:
    return DataflowExecutor(
        ScriptedModelClient(responses, **kwargs),
        predicates=DictPredicateRegistry(predicates) if predicates else None,
    )


async def test_linear_chain_runs_in_order_and_returns_last_output():
    graph = TopologyGraph(
        nodes=[node("planner", role_type=RoleType.ORCHESTRATOR), node("writer")],
        edges=[AgentEdge(source="planner", target="writer", label="plan")],
        entry=["planner"],
        outputs=["writer"],
    )
    result = await executor({"planner": "PLAN", "writer": "FINAL"}).rollout(graph, TASK)

    assert result.status is RolloutStatus.COMPLETED
    assert result.output == "FINAL"
    assert [i.node_id for i in result.trace.invocations] == ["planner", "writer"]
    assert [i.round_index for i in result.trace.invocations] == [0, 1]
    assert result.usage.total_tokens > 0


async def test_upstream_output_reaches_downstream_prompt():
    graph = TopologyGraph(
        nodes=[node("planner"), node("writer")],
        edges=[AgentEdge(source="planner", target="writer", label="plan")],
        entry=["planner"],
        outputs=["writer"],
    )
    result = await executor({"planner": "STEP-ONE", "writer": "done"}).rollout(graph, TASK)

    writer_prompt = result.trace.invocations_of("writer")[0].prompt[-1].content
    assert "STEP-ONE" in writer_prompt
    assert "# From: plan" in writer_prompt
    assert TASK.input in writer_prompt


async def test_fan_out_fan_in_waits_for_all_branches():
    graph = TopologyGraph(
        nodes=[node("split"), node("left"), node("right"), node("merge")],
        edges=[
            AgentEdge(source="split", target="left"),
            AgentEdge(source="split", target="right"),
            AgentEdge(source="left", target="merge", label="left"),
            AgentEdge(source="right", target="merge", label="right"),
        ],
        entry=["split"],
        outputs=["merge"],
    )
    result = await executor(
        {"split": "S", "left": "L", "right": "R", "merge": "M"}
    ).rollout(graph, TASK)

    merge_invocation = result.trace.invocations_of("merge")[0]
    assert merge_invocation.round_index == 2, "merge must wait a full round for both branches"
    assert {a.label for a in merge_invocation.inputs} == {"left", "right"}
    assert FailureSignal.JOIN_RELAXED not in result.trace.failure_signals


async def test_parallel_branches_run_in_the_same_round():
    graph = TopologyGraph(
        nodes=[node("split"), node("left"), node("right")],
        edges=[
            AgentEdge(source="split", target="left"),
            AgentEdge(source="split", target="right"),
        ],
        entry=["split"],
        outputs=["left", "right"],
    )
    result = await executor({"split": "S", "left": "L", "right": "R"}).rollout(graph, TASK)

    rounds = {i.node_id: i.round_index for i in result.trace.invocations}
    assert rounds["left"] == rounds["right"] == 1
    assert result.output == "L\n\nR"


async def test_fanout_replicates_a_node_within_one_visit():
    graph = TopologyGraph(
        nodes=[
            node("sampler", role_type=RoleType.PARALLEL_WORKER, fanout=3),
            node("judge", join=JoinPolicy.ANY),
        ],
        edges=[AgentEdge(source="sampler", target="judge", label="attempt")],
        entry=["sampler"],
        outputs=["judge"],
    )
    result = await executor({"sampler": "attempt", "judge": "picked"}).rollout(graph, TASK)

    samples = result.trace.invocations_of("sampler")
    assert len(samples) == 3
    assert {s.replica for s in samples} == {0, 1, 2}
    assert all(s.visit == 1 for s in samples)
    assert len(result.trace.invocations_of("judge")[0].inputs) == 3


async def test_failed_predicate_blocks_a_branch():
    graph = TopologyGraph(
        nodes=[node("checker", role_type=RoleType.VERIFIER), node("fixer"), node("shipper")],
        edges=[
            AgentEdge(
                source="checker",
                target="fixer",
                condition=PredicateCondition(name="contains", args={"needle": "FAIL"}),
            ),
            AgentEdge(
                source="checker",
                target="shipper",
                condition=PredicateCondition(
                    name="contains", args={"needle": "FAIL"}, negate=True
                ),
            ),
        ],
        entry=["checker"],
        outputs=["shipper"],
    )
    result = await executor(
        {"checker": "PASS looks good", "shipper": "shipped"},
        predicates={"contains": lambda args, payload: args["needle"] in payload},
    ).rollout(graph, TASK)

    checker = result.trace.invocations_of("checker")[0]
    assert checker.routed_edges == ["checker->shipper#"]
    assert checker.blocked_edges == ["checker->fixer#"]
    assert result.trace.invocations_of("fixer") == []
    assert result.output == "shipped"


async def test_llm_router_condition_routes_on_model_verdict():
    graph = TopologyGraph(
        nodes=[node("drafter"), node("polisher")],
        edges=[
            AgentEdge(
                source="drafter",
                target="polisher",
                condition=LLMRouterCondition(question="Does this need polish?"),
            )
        ],
        entry=["drafter"],
        outputs=["polisher"],
    )
    client = ScriptedModelClient(
        default=lambda req: "YES" if "router_edge" in req.metadata else "draft"
    )
    result = await DataflowExecutor(client).rollout(graph, TASK)

    assert result.trace.invocations_of("polisher")
    assert result.output == "draft"


async def test_unsatisfiable_join_is_relaxed_rather_than_deadlocked():
    graph = TopologyGraph(
        nodes=[node("router"), node("a"), node("b"), node("merge")],
        edges=[
            AgentEdge(
                source="router",
                target="a",
                condition=PredicateCondition(name="never"),
            ),
            AgentEdge(source="router", target="b"),
            AgentEdge(source="a", target="merge", label="a"),
            AgentEdge(source="b", target="merge", label="b"),
        ],
        entry=["router"],
        outputs=["merge"],
    )
    result = await executor(
        {"router": "go", "b": "B", "merge": "MERGED"},
        predicates={"never": lambda args, payload: False},
    ).rollout(graph, TASK)

    assert FailureSignal.JOIN_RELAXED in result.trace.failure_signals
    assert result.output == "MERGED"


async def test_loop_terminates_at_the_visit_cap():
    graph = TopologyGraph(
        nodes=[
            node("writer", join=JoinPolicy.ANY, max_visits=2),
            node("critic", role_type=RoleType.CRITIC, max_visits=2),
        ],
        edges=[
            AgentEdge(source="writer", target="critic", label="draft"),
            AgentEdge(source="critic", target="writer", label="critique"),
        ],
        entry=["writer"],
        outputs=["writer"],
    )
    result = await executor({"writer": "draft", "critic": "critique"}).rollout(graph, TASK)

    assert len(result.trace.invocations_of("writer")) == 2
    assert len(result.trace.invocations_of("critic")) == 2
    assert FailureSignal.VISIT_CAP_HIT in result.trace.failure_signals
    assert result.status is RolloutStatus.COMPLETED


async def test_step_budget_truncates_the_rollout():
    graph = TopologyGraph(
        nodes=[node("a"), node("b"), node("c")],
        edges=[AgentEdge(source="a", target="b"), AgentEdge(source="b", target="c")],
        entry=["a"],
        outputs=["c"],
        budget=GraphBudget(max_steps=2),
    )
    result = await executor().rollout(graph, TASK)

    assert result.status is RolloutStatus.BUDGET_EXHAUSTED
    assert FailureSignal.STEP_BUDGET_EXHAUSTED in result.trace.failure_signals
    assert len(result.trace.invocations) == 2
    assert result.output == ""


async def test_context_budget_truncation_is_reported():
    graph = TopologyGraph(
        nodes=[node("verbose"), node("cramped", context_budget=1)],
        edges=[AgentEdge(source="verbose", target="cramped")],
        entry=["verbose"],
        outputs=["cramped"],
    )
    result = await executor({"verbose": "x" * 5000, "cramped": "ok"}).rollout(graph, TASK)

    assert FailureSignal.CONTEXT_TRUNCATED in result.trace.failure_signals
    assert result.status is RolloutStatus.COMPLETED


async def test_edge_transform_trims_payload():
    graph = TopologyGraph(
        nodes=[node("verbose"), node("reader")],
        edges=[
            AgentEdge(
                source="verbose",
                target="reader",
                transform=ContentTransform(kind="raw", max_tokens=10),
            )
        ],
        entry=["verbose"],
        outputs=["reader"],
    )
    result = await executor({"verbose": "y" * 4000, "reader": "ok"}).rollout(graph, TASK)

    delivered = result.trace.invocations_of("reader")[0].inputs[0].content
    assert 0 < len(delivered) <= 40


async def test_field_transform_extracts_json_path():
    graph = TopologyGraph(
        nodes=[node("extractor"), node("reader")],
        edges=[
            AgentEdge(
                source="extractor",
                target="reader",
                transform=ContentTransform(kind="field", field="result.answer"),
            )
        ],
        entry=["extractor"],
        outputs=["reader"],
    )
    result = await executor(
        {"extractor": '{"result": {"answer": "42"}, "scratch": "noise"}', "reader": "ok"}
    ).rollout(graph, TASK)

    assert result.trace.invocations_of("reader")[0].inputs[0].content == "42"


async def test_provider_error_is_contained_and_flagged():
    def explode(_request):
        raise RuntimeError("provider down")

    graph = TopologyGraph(
        nodes=[node("a"), node("b")],
        edges=[AgentEdge(source="a", target="b")],
        entry=["a"],
        outputs=["b"],
    )
    result = await DataflowExecutor(ScriptedModelClient(default=explode)).rollout(graph, TASK)

    assert FailureSignal.NODE_ERROR in result.trace.failure_signals
    assert result.status is RolloutStatus.NO_OUTPUT
    assert "provider down" in (result.trace.invocations_of("a")[0].error or "")


async def test_trace_is_serializable():
    graph = TopologyGraph(
        nodes=[node("a")],
        entry=["a"],
        outputs=["a"],
    )
    result = await executor({"a": "answer"}).rollout(graph, TASK)

    payload = result.model_dump_json()
    assert '"answer"' in payload
    assert result.trace.graph_semantic_hash == graph.semantic_hash
