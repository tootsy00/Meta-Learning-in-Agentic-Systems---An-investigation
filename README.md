# Agentic Architecture Search (AAS)

An optimization engine that discovers multi-agent topologies — which agents
exist, what they run on, and how they are wired — for a given task, by searching
over serializable graph candidates and scoring them on a quality/latency/cost
objective.

**Status: Phase 1, Steps 1–2.** The candidate representation and the execution
engine are implemented and tested. The optimizer, benchmark harness, and
repository roadmap (Steps 3–5) are not yet designed — see
[`docs/blueprint/00-overview.md`](docs/blueprint/00-overview.md) for the open
questions blocking them.

## Design record

| Document | Contents |
| --- | --- |
| [`00-overview.md`](docs/blueprint/00-overview.md) | Assumptions, deferred work, open questions |
| [`01-graph-schema.md`](docs/blueprint/01-graph-schema.md) | `AgentNode` / `AgentEdge` / `TopologyGraph`, validation, JSON serde, identity hashing |
| [`02-execution-engine.md`](docs/blueprint/02-execution-engine.md) | Execution contracts, the round-based scheduler, budgets, trace and failure signals |

## Layout

```
src/aas/core/graph/schema.py    candidate representation: nodes, edges, serde, diagnostics
src/aas/core/engine/protocols.py  ModelClient, ToolRegistry, NodeRunner, GraphExecutor
src/aas/core/engine/trace.py      TaskInstance, RolloutTrace, FailureSignal, RolloutResult
src/aas/core/engine/dataflow.py   reference round-based executor
src/aas/core/engine/prompts.py    prompt assembly and context-budget enforcement
src/aas/core/engine/stub.py       deterministic test doubles
examples/reflexive_writer.py      a hand-written candidate, run end to end
```

## Try it

```bash
pip install -e ".[dev]"
pytest                              # 33 tests, no network
python examples/reflexive_writer.py # a full rollout against the scripted client
```

Building a candidate and running it:

```python
from aas.core.engine import DataflowExecutor, TaskInstance
from aas.core.engine.stub import ScriptedModelClient
from aas.core.graph import AgentEdge, AgentNode, RoleType, TopologyGraph

graph = TopologyGraph(
    nodes=[
        AgentNode(id="planner", role_type=RoleType.ORCHESTRATOR, model_id="openai/gpt-4o"),
        AgentNode(id="writer", role_type=RoleType.WORKER, model_id="openai/gpt-4o-mini"),
    ],
    edges=[AgentEdge(source="planner", target="writer", label="plan")],
    entry=["planner"],
    outputs=["writer"],
)

assert graph.diagnose() == []                                  # semantic health
assert TopologyGraph.from_json(graph.to_json()).semantic_hash == graph.semantic_hash

result = await DataflowExecutor(ScriptedModelClient()).rollout(
    graph, TaskInstance(id="t1", input="Explain gradient descent.")
)
result.output, result.usage.total_tokens, result.trace.failure_signals
```

No provider key is needed anywhere in the current codebase: `ModelClient` is a
protocol, and the only implementation so far is a deterministic stub.
