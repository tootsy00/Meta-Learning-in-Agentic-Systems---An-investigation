# Step 2 — Multi-agent execution engine abstraction

Implementation: `src/aas/core/engine/`. Tests: `tests/test_dataflow.py`.

## The one contract that matters

```python
class GraphExecutor(Protocol):
    async def rollout(self, graph: TopologyGraph, task: TaskInstance) -> RolloutResult: ...
```

A candidate plus an example goes in; an answer, a cost accounting, and a full
trace come out. Everything else in this layer exists to make that signature
implementable by more than one backend.

## Why a scheduler of our own

LangGraph and AutoGen are good runtimes and bad search substrates, for three
reasons:

1. **The candidate must be data.** Their graphs are built from Python callables.
   Ours has to be a JSON document that a mutator can edit and a hash can identify.
2. **The trace is the training signal.** We need per-invocation prompts, token
   accounting, routing decisions, and blocked edges in a serializable object.
   Callback-based tracing gives us less and costs more to normalize.
3. **Search generates adversarial topologies.** Unbounded critic↔worker
   ping-pong and forty-way fan-outs will appear in generation one. The engine has
   to truncate them cheaply and score the truncated rollout rather than hang.

So `GraphExecutor` is a protocol and `DataflowExecutor` is the semantics
reference. A LangGraph backend can be added later as a *compilation target*
(`TopologyGraph` → `StateGraph`); `tests/test_dataflow.py` is the conformance
suite it would have to pass. LiteLLM sits one layer lower, behind `ModelClient`,
which is where it belongs: the executor should not know what a provider is.

## Execution model: bulk-synchronous rounds

```
seed entry nodes with the task input
loop:
  0. budget check -> truncate and exit if exceeded
  1. select every node whose inbox satisfies its join policy
  2. run them concurrently, each expanded into `fanout` replicas
  3. for each outbound edge: evaluate condition, transform payload, deliver
  4. next round
```

Rounds rather than a free-running event loop, because the trace has to be
readable by an LLM in Step 3. Round indices give reflection a clean notion of
"what happened at the same time" and make invocation ordering deterministic even
though execution inside a round is concurrent (`asyncio.gather` under a
`max_concurrency` semaphore).

**Join policies.** `all` waits for every inbound edge, `any` fires on the first
arrival, `k_of_n` on k distinct edges. A seeded task activation always fires its
entry node, so an entry node that also sits on a loop is not deadlocked at
round 0.

**Join relaxation instead of deadlock.** An `all` join whose upstream branch was
pruned by a routing predicate would wait forever. When a round finds nothing
runnable while activations are still pending, the engine fires the pending nodes
on partial input *once*, records a `join_relaxed` event, and continues. A
candidate that hangs produces no signal; a candidate that degrades produces a
score and a labelled defect. The second is worth far more to the optimizer.

**Loops.** A cycle iterates while its nodes have visits remaining. On hitting
`max_visits` the pending payload is discarded and `visit_cap_hit` is recorded —
so a runaway loop terminates, is scored, and is diagnosable.

## Layer boundaries

| Protocol | Responsibility | Reference implementation |
| --- | --- | --- |
| `ModelClient` | `complete(LLMRequest) -> LLMResponse`, `count_tokens` | `ScriptedModelClient` (LiteLLM adapter is Step 5) |
| `ToolRegistry` | resolve `tool_access` names to callables | `DictToolRegistry` |
| `PredicateRegistry` | resolve `PredicateCondition.name` for routing | `DictPredicateRegistry` |
| `NodeRunner` | one node's inbox → one output | `LLMNodeRunner` |
| `ResponseCache` | memoize on (node identity, prompt) | declared only |
| `GraphExecutor` | orchestrate a rollout | `DataflowExecutor` |

`NodeRunner` is the extension point that keeps the scheduler small. A ReAct
tool-loop runner, a retrieval node, or a deterministic Python aggregator all
enter the search space by implementing this one method — the scheduler never
learns they exist. A runner receives a `NodeContext` (its inbox, its services)
and *no handle to the scheduler*, so it cannot mutate control flow implicitly and
can be unit-tested alone.

Prompt assembly is separated again into `DefaultPromptCompiler`, because it is
itself searchable: role preamble plus strategy scaffold plus the node's
`instructions`, with `context_budget` enforced by proportional truncation of
inbound sections (the task input is never truncated). Truncation raises the
`context_truncated` signal rather than happening silently — context bloat is a
failure mode we intend to optimize against, so it must be observable.

A missing predicate raises `ExecutionConfigError` instead of routing `False`.
Silently blocking would let the optimizer score a candidate whose routing never
fired and conclude the branch was useless. The search space is responsible for
only emitting registered predicate names.

## Budgets

`GraphBudget` is enforced by `BudgetTracker` before each round: `max_steps`,
`max_total_tokens`, `max_wall_clock_s`, `max_usd`, plus `max_concurrency` and a
per-node `timeout_s`. Exceeding any of them truncates the rollout, sets
`RolloutStatus.BUDGET_EXHAUSTED`, and records which limit was hit. Provider
exceptions are caught per invocation and recorded as `node_error` — one flaky
call must not void an otherwise informative rollout.

## What a rollout returns

```python
RolloutResult(task_id, output, status, usage, latency_s, trace)
```

with `usage` and `latency_s` feeding the β and γ terms of the objective directly,
and accuracy supplied later by the evaluator (see assumption 5 in the overview).

The trace carries every `NodeInvocation` — node, round, visit, replica, inputs,
compiled prompt, output, usage, duration, error, and the edges it routed to
versus blocked — plus engine `TraceEvent`s and a list of `FailureSignal`s.

The signals the engine emits mechanically today:

`step_budget_exhausted`, `token_budget_exhausted`, `wall_clock_exhausted`,
`cost_budget_exhausted`, `node_timeout`, `node_error`, `context_truncated`,
`join_relaxed`, `visit_cap_hit`, `no_output_produced`, `dead_branch`.

Higher-order pathologies from your Step 4 list — semantic step repetition,
unproductive critic loops, context bloat trends across visits — are *derived*
detectors that post-process this same trace. They need no engine changes, which
is the main reason the trace is a typed model rather than log lines. Note that
`dead_branch` is informational, not a defect: a router that correctly skips a
branch produces it too.

## Verified semantics

`tests/test_dataflow.py` pins the behaviour any backend must reproduce: ordering
in a linear chain, upstream output reaching the downstream prompt, fan-in waiting
a full round for both branches, parallel branches sharing a round, `fanout`
replication within one visit, predicate routing blocking a branch, LLM-router
verdicts, join relaxation, loop termination at the visit cap, step-budget
truncation, context-budget truncation, edge payload trimming and JSON field
extraction, contained provider errors, and trace serializability.

## Not yet built

The ReAct tool loop (scaffold emitted, cycles not driven), a model-backed
`summary` transform (head-truncates today), `ResponseCache` (protocol only), and
the LiteLLM client. Each has its extension point defined above; none of them
changes the contracts on this page.
