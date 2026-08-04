import pytest
from pydantic import ValidationError

from aas.core.graph import (
    AgentEdge,
    AgentNode,
    JoinPolicy,
    PredicateCondition,
    RoleType,
    TopologyGraph,
)


def node(node_id: str, **kwargs) -> AgentNode:
    kwargs.setdefault("role_type", RoleType.WORKER)
    kwargs.setdefault("model_id", "openai/gpt-4o-mini")
    return AgentNode(id=node_id, **kwargs)


def linear_graph() -> TopologyGraph:
    return TopologyGraph(
        name="linear",
        nodes=[node("planner", role_type=RoleType.ORCHESTRATOR), node("writer")],
        edges=[AgentEdge(source="planner", target="writer", label="plan")],
        entry=["planner"],
        outputs=["writer"],
    )


class TestStructuralInvariants:
    def test_duplicate_node_ids_rejected(self):
        with pytest.raises(ValidationError, match="duplicate node ids"):
            TopologyGraph(nodes=[node("a"), node("a")], entry=["a"], outputs=["a"])

    def test_dangling_edge_rejected(self):
        with pytest.raises(ValidationError, match="unknown node"):
            TopologyGraph(
                nodes=[node("a")],
                edges=[AgentEdge(source="a", target="ghost")],
                entry=["a"],
                outputs=["a"],
            )

    def test_duplicate_edges_rejected(self):
        with pytest.raises(ValidationError, match="duplicate edges"):
            TopologyGraph(
                nodes=[node("a"), node("b")],
                edges=[AgentEdge(source="a", target="b"), AgentEdge(source="a", target="b")],
                entry=["a"],
                outputs=["b"],
            )

    def test_parallel_edges_allowed_when_labelled(self):
        graph = TopologyGraph(
            nodes=[node("a"), node("b", join=JoinPolicy.ANY)],
            edges=[
                AgentEdge(source="a", target="b", label="draft"),
                AgentEdge(source="a", target="b", label="critique"),
            ],
            entry=["a"],
            outputs=["b"],
        )
        assert len(graph.inbound("b")) == 2

    def test_unknown_entry_rejected(self):
        with pytest.raises(ValidationError, match="entry references unknown"):
            TopologyGraph(nodes=[node("a")], entry=["b"], outputs=["a"])

    def test_join_k_requires_k(self):
        with pytest.raises(ValidationError, match="requires join_k"):
            node("a", join=JoinPolicy.K_OF_N)


class TestDiagnostics:
    def test_healthy_graph_has_no_issues(self):
        assert linear_graph().diagnose() == []

    def test_unreachable_node_reported_not_raised(self):
        graph = TopologyGraph(
            nodes=[node("a"), node("orphan")],
            edges=[],
            entry=["a"],
            outputs=["a"],
        )
        codes = {i.code for i in graph.diagnose()}
        assert "unreachable_node" in codes
        assert "no_input" in codes

    def test_cycle_without_visit_budget_reported(self):
        graph = TopologyGraph(
            nodes=[node("writer"), node("critic", role_type=RoleType.CRITIC)],
            edges=[
                AgentEdge(source="writer", target="critic"),
                AgentEdge(source="critic", target="writer"),
            ],
            entry=["writer"],
            outputs=["writer"],
        )
        issues = {i.code for i in graph.diagnose()}
        assert "cycle_without_visit_budget" in issues

    def test_cycle_with_visit_budget_is_healthy(self):
        graph = TopologyGraph(
            nodes=[
                node("writer", max_visits=3, join=JoinPolicy.ANY),
                node("critic", role_type=RoleType.CRITIC, max_visits=3),
            ],
            edges=[
                AgentEdge(source="writer", target="critic"),
                AgentEdge(source="critic", target="writer"),
            ],
            entry=["writer"],
            outputs=["writer"],
        )
        assert graph.diagnose() == []

    def test_unsatisfiable_join_reported(self):
        graph = TopologyGraph(
            nodes=[node("a"), node("b", join=JoinPolicy.K_OF_N, join_k=3)],
            edges=[AgentEdge(source="a", target="b")],
            entry=["a"],
            outputs=["b"],
        )
        assert any(i.code == "join_k_exceeds_inbound" for i in graph.diagnose())


class TestSerialization:
    def test_json_round_trip_is_lossless(self):
        original = linear_graph()
        restored = TopologyGraph.from_json(original.to_json())
        assert restored.model_dump() == original.model_dump()

    def test_discriminated_condition_survives_round_trip(self):
        graph = TopologyGraph(
            nodes=[node("a"), node("b")],
            edges=[
                AgentEdge(
                    source="a",
                    target="b",
                    condition=PredicateCondition(name="contains", args={"needle": "PASS"}),
                )
            ],
            entry=["a"],
            outputs=["b"],
        )
        restored = TopologyGraph.from_json(graph.to_json())
        condition = restored.edges[0].condition
        assert isinstance(condition, PredicateCondition)
        assert condition.args == {"needle": "PASS"}

    def test_semantic_hash_ignores_identity_fields(self):
        a = linear_graph()
        b = a.clone(name="renamed")
        assert a.id != b.id
        assert a.semantic_hash == b.semantic_hash

    def test_semantic_hash_is_order_independent(self):
        a = linear_graph()
        b = a.model_copy(update={"nodes": list(reversed(a.nodes))})
        assert a.semantic_hash == b.semantic_hash

    def test_prompt_edit_changes_semantic_hash_but_not_structure_hash(self):
        a = linear_graph()
        b = a.clone()
        b.nodes[1].instructions = "Write in the style of a haiku."
        assert a.semantic_hash != b.semantic_hash
        assert a.structure_hash == b.structure_hash

    def test_rewiring_changes_structure_hash(self):
        a = linear_graph()
        b = a.clone()
        b.edges[0].label = "outline"
        assert a.structure_hash != b.structure_hash

    def test_clone_is_deep(self):
        original = linear_graph()
        copy = original.clone()
        copy.nodes[0].temperature = 1.5
        assert original.nodes[0].temperature != 1.5
