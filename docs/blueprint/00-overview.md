# Phase 1 blueprint — overview

This directory is the design record for Agentic Architecture Search. It covers
**Step 1 (graph representation)** and **Step 2 (execution engine)**, both of
which are implemented as working code under `src/aas/core/` so the contracts can
be reviewed against something that actually runs. Steps 3–5 (optimizer,
benchmarking, roadmap) are deferred until these two are agreed.

## Assumptions I made

These were not stated in the brief. If any is wrong, say so now — they are load
bearing for everything downstream.

1. **Python, not TypeScript.** The optimizer, the eval harness, and every model
   SDK we would plug in are Python. A TS schema would need a second source of
   truth.
2. **A candidate is pure data.** No callables, clients, or closures may appear in
   a `TopologyGraph`. Routing predicates and tools are stored as *names* resolved
   against a registry at execution time. This is what makes candidates
   serializable, hashable, diffable, and shippable to worker processes.
3. **Prompt text is part of the search space.** The brief's node attributes omit
   the instruction string, but a GEPA-style reflective optimizer edits prompts as
   readily as it rewires edges. `AgentNode.instructions` is therefore a
   first-class searchable field.
4. **Role type is semantic, not structural.** `role_type` selects a prompt
   scaffold and gives reflection a vocabulary; it does not drive control flow.
   All control flow lives on edges and node join policies. Consequence for your
   spec: `Parallel-Worker` is a label, while actual parallelism comes from
   fan-out edges (several targets) or `AgentNode.fanout` (n independent replicas
   of one node).
5. **Scoring lives outside the engine.** `RolloutResult` carries usage, latency,
   and a trace, but no accuracy field. Keeping the objective out means a stored
   rollout can be re-scored under a different α/β/γ without re-running the graph
   — which matters a lot when you retune the objective mid-search.
6. **Tasks are single-shot.** A `TaskInstance` is an input string plus an
   optional reference. Interactive environments (a task that responds to agent
   actions over several turns) would change this type; see the open questions.

## What Step 1 and Step 2 deliver

| Concern | Module | Status |
| --- | --- | --- |
| Candidate representation | `aas.core.graph.schema` | implemented, 18 tests |
| Structural + semantic validation | `TopologyGraph.diagnose()` | implemented |
| JSON serde and identity hashing | `to_json` / `from_json` / `*_hash` | implemented |
| Execution contracts | `aas.core.engine.protocols` | implemented |
| Trace and failure taxonomy | `aas.core.engine.trace` | implemented |
| Reference scheduler | `aas.core.engine.dataflow` | implemented, 15 tests |
| Deterministic test doubles | `aas.core.engine.stub` | implemented |

Read `01-graph-schema.md` and `02-execution-engine.md` for the rationale behind
each, and run `python examples/reflexive_writer.py` for an end-to-end rollout
that needs no API key.

## Deliberately deferred

Left out to keep Phase 1 reviewable, each with a defined extension point:

- **LiteLLM-backed client.** `ModelClient` is a protocol with a scripted stub
  behind it; the real adapter is ~40 lines and adds nothing to the design review.
- **ReAct tool loop.** The scaffold is emitted, but the reference runner is
  single-shot. Driving tool cycles is a separate `NodeRunner` implementation.
- **Fan-out sharding.** `fanout` currently means n independent attempts
  (self-consistency). Splitting a list across replicas needs a splitter contract.
- **Model-backed edge summarization.** `ContentTransform(kind="summary")`
  head-truncates today; a summarizer is a drop-in once its cost enters the
  objective.
- **Response caching.** `ResponseCache` is declared because it is the single
  biggest cost lever in the search loop (sibling candidates share most nodes),
  but not implemented.

## Open questions for you

1. **Are budgets part of the genome?** Today `GraphBudget` lives inside the
   candidate and inside its semantic hash, so the optimizer can search over
   token and step limits. That is genuinely part of the quality/cost Pareto
   surface, but it also lets a candidate look cheap by starving itself, and it
   makes cross-candidate comparison noisier. The alternative is a fixed harness
   budget for all candidates. Which do you want?
2. **Typed edge payloads?** Payloads are free text. Declaring a JSON schema per
   edge would shrink the search space and make fan-in far more reliable, at the
   cost of constraining what the models can emit. Worth it?
3. **Loop expressiveness.** Loops are currently just cycles plus a per-node
   `max_visits` cap. Do you want an explicit supervisor-loop construct with a
   named exit condition, or is a cycle with a visit cap and a routing predicate
   enough?
4. **Is `tool_access` searchable?** It is today. That means the optimizer can
   grant a node a tool it was not given by hand, which is powerful and also a
   safety surface. Should the search space allow-list be per-role?
5. **Objective normalization.** α(1−acc) + β·latency + γ·cost mixes units;
   latency in seconds and cost in dollars need per-benchmark scaling before the
   weights mean anything. Note that Pareto selection does not need scalarization
   at all — it can rank on the raw vector, and the scalar loss is only needed for
   final reporting. I would default to keeping the vector and normalizing only
   for logging. Confirm before Step 3.
