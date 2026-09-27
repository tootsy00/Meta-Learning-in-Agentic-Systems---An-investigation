"""Serializable description of a candidate multi-agent topology.

A `TopologyGraph` is the unit that the search operates on: it is produced by a
mutator, hashed for deduplication, persisted to JSON, executed by an engine, and
scored. Everything needed to reproduce a rollout lives in this object; nothing in
here may hold live handles (clients, sockets, callables), because candidates are
copied, logged, and shipped between processes.

Two levels of checking are deliberately separated:

* **Structural invariants** are enforced by Pydantic validators and make a graph
  impossible to construct in a broken state (dangling edge, duplicate node id).
* **Semantic health** is reported by :meth:`TopologyGraph.diagnose` as a list of
  issues. Mutation produces transiently unhealthy graphs (an orphaned node after
  ``prune_edge``, for instance), and the optimizer needs to inspect and repair
  those rather than be blocked by an exception.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

NodeId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")]


class RoleType(StrEnum):
    """Semantic label for a node.

    The role does *not* drive control flow -- that is entirely a property of the
    edges. It selects the prompt scaffold family and the default policies applied
    at compile time, and gives the reflection step a vocabulary for reasoning
    about traces ("the verifier never rejected anything").
    """

    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    PARALLEL_WORKER = "parallel_worker"
    VERIFIER = "verifier"
    CRITIC = "critic"


class PromptStrategy(StrEnum):
    DIRECT = "direct"
    COT = "cot"
    REACT = "react"
    FEW_SHOT = "few_shot"


class JoinPolicy(StrEnum):
    """When a node with several inbound edges becomes runnable."""

    ALL = "all"
    ANY = "any"
    K_OF_N = "k_of_n"


class MergePolicy(StrEnum):
    """How several inbound activations are folded into one prompt context."""

    CONCAT = "concat"
    FIRST = "first"
    MAJORITY_VOTE = "majority_vote"


class FewShotExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str
    output: str


class AgentNode(BaseModel):
    """A single agent in the topology.

    Every field here is part of the search space. `instructions` is included
    because a reflective optimizer edits prompt text as readily as it rewires
    edges; a topology whose prompts are external is only half-searchable.
    """

    model_config = ConfigDict(extra="forbid")

    id: NodeId
    role_type: RoleType
    model_id: str = Field(min_length=1, description="Provider-qualified, e.g. 'openai/gpt-4o'.")

    instructions: str = ""
    prompt_strategy: PromptStrategy = PromptStrategy.DIRECT
    few_shot_examples: list[FewShotExample] = Field(default_factory=list)

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    context_budget: int = Field(default=8000, gt=0, description="Max input tokens after merge.")
    max_output_tokens: int = Field(default=1024, gt=0)

    tool_access: list[str] = Field(default_factory=list)

    join: JoinPolicy = JoinPolicy.ALL
    join_k: int | None = Field(default=None, ge=1)
    merge: MergePolicy = MergePolicy.CONCAT

    fanout: int = Field(
        default=1,
        ge=1,
        description="Run this many independent copies per activation (self-consistency).",
    )
    max_visits: int = Field(
        default=1,
        ge=1,
        description="How many times the node may run in one rollout; >1 permits loops.",
    )
    timeout_s: float = Field(default=120.0, gt=0)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_join_k(self) -> AgentNode:
        if self.join is JoinPolicy.K_OF_N and self.join_k is None:
            raise ValueError(f"node {self.id!r}: join='k_of_n' requires join_k")
        if self.join is not JoinPolicy.K_OF_N and self.join_k is not None:
            raise ValueError(f"node {self.id!r}: join_k is only meaningful with join='k_of_n'")
        return self


class AlwaysCondition(BaseModel):
    """Unconditional edge."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["always"] = "always"


class PredicateCondition(BaseModel):
    """Deterministic routing via a named predicate resolved at execution time.

    Keeping the predicate as a name plus arguments (rather than a lambda) is what
    lets a graph survive a JSON round trip.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["predicate"] = "predicate"
    name: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    negate: bool = False


class LLMRouterCondition(BaseModel):
    """Routing decided by asking a model a yes/no question about the payload."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["llm_router"] = "llm_router"
    question: str = Field(min_length=1)
    model_id: str | None = Field(default=None, description="Defaults to the source node's model.")


EdgeCondition = Annotated[
    AlwaysCondition | PredicateCondition | LLMRouterCondition,
    Field(discriminator="kind"),
]


class ContentTransform(BaseModel):
    """What part of the source output travels down the edge.

    Context bloat is one of the failure modes we expect to optimize away, so the
    edge -- not the receiving node -- owns payload shaping.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["raw", "field", "summary"] = "raw"
    field: str | None = Field(default=None, description="Dotted path, for kind='field'.")
    max_tokens: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_field(self) -> ContentTransform:
        if self.kind == "field" and not self.field:
            raise ValueError("transform kind='field' requires a field path")
        return self


class AgentEdge(BaseModel):
    """A directed channel carrying one node's output into another's context."""

    model_config = ConfigDict(extra="forbid")

    source: NodeId
    target: NodeId
    label: str | None = Field(
        default=None,
        description="Channel name surfaced to the target ('draft', 'critique'). "
        "Also disambiguates parallel edges between the same pair.",
    )
    condition: EdgeCondition = Field(default_factory=AlwaysCondition)
    transform: ContentTransform = Field(default_factory=ContentTransform)

    @property
    def key(self) -> str:
        return f"{self.source}->{self.target}#{self.label or ''}"


class GraphBudget(BaseModel):
    """Hard caps enforced by the engine, not suggestions to the agents."""

    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=32, gt=0, description="Total node invocations per rollout.")
    max_total_tokens: int = Field(default=200_000, gt=0)
    max_wall_clock_s: float = Field(default=300.0, gt=0)
    max_concurrency: int = Field(default=8, gt=0)
    max_usd: float | None = Field(default=None, gt=0)


class GraphLineage(BaseModel):
    """Provenance, so the optimizer can attribute score deltas to mutations."""

    model_config = ConfigDict(extra="forbid")

    parent_ids: list[str] = Field(default_factory=list)
    mutation: str | None = None
    generation: int = 0
    notes: str | None = None


class GraphIssue(BaseModel):
    """A semantic problem found by :meth:`TopologyGraph.diagnose`."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    node_ids: list[str] = Field(default_factory=list)


class TopologyGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""

    nodes: list[AgentNode]
    edges: list[AgentEdge] = Field(default_factory=list)
    entry: list[NodeId] = Field(min_length=1, description="Nodes seeded with the task input.")
    outputs: list[NodeId] = Field(min_length=1, description="Nodes whose output is the answer.")

    budget: GraphBudget = Field(default_factory=GraphBudget)
    lineage: GraphLineage = Field(default_factory=GraphLineage)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_structure(self) -> TopologyGraph:
        ids = [n.id for n in self.nodes]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate node ids: {sorted(duplicates)}")
        known = set(ids)

        for edge in self.edges:
            missing = {edge.source, edge.target} - known
            if missing:
                raise ValueError(f"edge {edge.key} references unknown node(s) {sorted(missing)}")

        keys = [e.key for e in self.edges]
        dup_edges = {k for k in keys if keys.count(k) > 1}
        if dup_edges:
            raise ValueError(f"duplicate edges (give them distinct labels): {sorted(dup_edges)}")

        for field in ("entry", "outputs"):
            unknown = set(getattr(self, field)) - known
            if unknown:
                raise ValueError(f"{field} references unknown node(s) {sorted(unknown)}")

        return self

    # -- lookups ---------------------------------------------------------

    @property
    def node_index(self) -> dict[str, AgentNode]:
        return {n.id: n for n in self.nodes}

    def node(self, node_id: str) -> AgentNode:
        return self.node_index[node_id]

    def inbound(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.target == node_id]

    def outbound(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.source == node_id]

    def to_networkx(self) -> nx.MultiDiGraph:
        """Analysis view. Mutators and diagnostics use this; execution does not."""
        g = nx.MultiDiGraph()
        for node in self.nodes:
            g.add_node(node.id, role_type=node.role_type.value, max_visits=node.max_visits)
        for edge in self.edges:
            g.add_edge(edge.source, edge.target, key=edge.key, condition=edge.condition.kind)
        return g

    # -- semantic health -------------------------------------------------

    def diagnose(self) -> list[GraphIssue]:
        """Report problems that make a graph wasteful or non-terminating.

        Returns issues instead of raising so that a mutator can produce a graph,
        inspect it, and repair it inside the same generation.
        """
        issues: list[GraphIssue] = []
        g = self.to_networkx()

        reachable: set[str] = set(self.entry)
        for entry in self.entry:
            reachable |= nx.descendants(g, entry)
        orphans = sorted({n.id for n in self.nodes} - reachable)
        if orphans:
            issues.append(
                GraphIssue(
                    code="unreachable_node",
                    message="node(s) cannot be reached from any entry point and will never run",
                    node_ids=orphans,
                )
            )

        never_read = sorted(o for o in self.outputs if o not in reachable)
        if never_read:
            issues.append(
                GraphIssue(
                    code="unreachable_output",
                    message="declared output node(s) are unreachable, so rollouts produce nothing",
                    node_ids=never_read,
                )
            )

        index = self.node_index
        for cycle in nx.simple_cycles(nx.DiGraph(g)):
            capped = [n for n in cycle if index[n].max_visits <= 1]
            if capped:
                issues.append(
                    GraphIssue(
                        code="cycle_without_visit_budget",
                        message="node(s) sit on a cycle but allow only one visit, "
                        "so the loop can never iterate",
                        node_ids=sorted(capped),
                    )
                )

        for node in self.nodes:
            inbound = self.inbound(node.id)
            if node.join is JoinPolicy.K_OF_N and node.join_k and node.join_k > len(inbound):
                issues.append(
                    GraphIssue(
                        code="join_k_exceeds_inbound",
                        message=f"join_k={node.join_k} but the node has {len(inbound)} inbound "
                        "edges, so the join can never be satisfied",
                        node_ids=[node.id],
                    )
                )
            if node.id not in self.entry and not inbound:
                issues.append(
                    GraphIssue(
                        code="no_input",
                        message="node is neither an entry point nor a target of any edge",
                        node_ids=[node.id],
                    )
                )

        return issues

    def is_healthy(self) -> bool:
        return not self.diagnose()

    # -- serialization ---------------------------------------------------

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=indent, sort_keys=False)

    @classmethod
    def from_json(cls, payload: str | bytes) -> TopologyGraph:
        return cls.model_validate_json(payload)

    def canonical_dict(self) -> dict[str, Any]:
        """Behaviour-determining fields only, in a stable order.

        Identity fields (`id`, `name`, `lineage`, `metadata`) are excluded so that
        two independently discovered candidates that behave identically hash the
        same.
        """
        payload = self.model_dump(mode="json")
        return {
            "schema_version": payload["schema_version"],
            "nodes": sorted(payload["nodes"], key=lambda n: n["id"]),
            "edges": sorted(
                payload["edges"], key=lambda e: (e["source"], e["target"], e["label"] or "")
            ),
            "entry": sorted(payload["entry"]),
            "outputs": sorted(payload["outputs"]),
            "budget": payload["budget"],
        }

    @property
    def semantic_hash(self) -> str:
        """Identity for caching and duplicate suppression in the population."""
        return _sha256(self.canonical_dict())

    @property
    def structure_hash(self) -> str:
        """Wiring-only identity: same shape, ignoring prompts, models and decoding.

        Lets the optimizer ask "have I already explored this skeleton?" separately
        from "have I already tried this exact candidate?".
        """
        skeleton = {
            "nodes": sorted((n.id, n.role_type.value) for n in self.nodes),
            "edges": sorted(
                (e.source, e.target, e.label or "", e.condition.kind) for e in self.edges
            ),
            "entry": sorted(self.entry),
            "outputs": sorted(self.outputs),
        }
        return _sha256(skeleton)

    def clone(self, **overrides: Any) -> TopologyGraph:
        """Deep copy with a fresh id -- the base operation of every mutator."""
        data = self.model_dump(mode="python")
        data.pop("id", None)
        data.update(overrides)
        return TopologyGraph.model_validate(data)


def _sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
