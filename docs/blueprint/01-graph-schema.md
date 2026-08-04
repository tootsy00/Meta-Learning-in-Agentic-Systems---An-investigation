# Step 1 — Data schema and graph representation

Implementation: `src/aas/core/graph/schema.py`. Tests: `tests/test_schema.py`.

## The shape of a candidate

```
TopologyGraph
├── schema_version, id, name
├── nodes:   list[AgentNode]
├── edges:   list[AgentEdge]
├── entry:   list[NodeId]      # seeded with the task input
├── outputs: list[NodeId]      # concatenated to form the answer
├── budget:  GraphBudget       # hard runtime caps
├── lineage: GraphLineage      # parents, mutation name, generation
└── metadata
```

`entry` and `outputs` are explicit rather than inferred from in-degree and
out-degree. Inference breaks the moment a graph contains a cycle — in a
writer↔critic loop the writer has both inbound and outbound edges, and the
optimizer must still be able to say "the writer is where the task enters and the
answer leaves".

## `AgentNode`

| Field | Why it is here |
| --- | --- |
| `role_type` | Semantic label → prompt scaffold + reflection vocabulary. Not control flow. |
| `model_id` | Provider-qualified (`openai/gpt-4o`), LiteLLM-style. |
| `instructions` | The mutable prompt body. **Added beyond your spec** — reflective optimizers edit this constantly. |
| `prompt_strategy`, `few_shot_examples` | Scaffold selection; examples only used by `few_shot`. |
| `temperature`, `context_budget`, `max_output_tokens` | Decoding and input-size control. |
| `tool_access` | Names resolved by a `ToolRegistry`. |
| `join`, `join_k` | When a multi-input node becomes runnable: `all`, `any`, `k_of_n`. |
| `merge` | How several inbound payloads fold into one context: `concat`, `first`, `majority_vote`. |
| `fanout` | n independent replicas per activation — self-consistency without n copies in the graph. |
| `max_visits` | Per-rollout visit cap; `>1` is what makes a cycle a loop rather than a hang. |
| `timeout_s` | Per-invocation wall clock. |

`join`/`merge`/`fanout`/`max_visits` are additions to your node spec. Without
them a fan-in node has no defined semantics, and a supervisor loop has no
termination condition — both are things the search will produce on its first
generation.

## `AgentEdge`

```python
AgentEdge(
    source="verifier",
    target="editor",
    label="rejection",                                   # channel name shown to the target
    condition=PredicateCondition(name="starts_with",     # discriminated union
                                 args={"prefix": "FAIL"}),
    transform=ContentTransform(kind="raw", max_tokens=1200),
)
```

Three deliberate choices:

- **Conditions are a discriminated union**, not code. `always` | `predicate`
  (named, registry-resolved, with `negate`) | `llm_router` (a yes/no question put
  to a model). A lambda would not survive a JSON round trip, and the search space
  must be enumerable for mutation to be well defined.
- **`transform` belongs to the edge, not the receiver.** Context bloat is one of
  the pathologies we expect to optimize away, so payload shaping (`raw`,
  `field` for a dotted JSON path, `summary`, plus `max_tokens`) is a property of
  the channel and is independently mutable.
- **`label` doubles as the parallel-edge discriminator.** Two edges between the
  same pair are legal iff their labels differ, which is what lets a critic send
  both a `critique` and a `revision` channel to the same writer.

Edge identity is the derived `key` (`source->target#label`), so edges need no ids
of their own and a mutated graph does not churn identifiers.

## Two levels of checking

This split matters for the optimizer, so it is worth being explicit.

**Structural invariants** are Pydantic validators and raise. A graph with a
dangling edge, a duplicate node id, or a duplicate edge key cannot be
constructed. These are always bugs.

**Semantic health** is `diagnose() -> list[GraphIssue]` and never raises:

| Code | Meaning |
| --- | --- |
| `unreachable_node` | never runs; wasted mutation |
| `unreachable_output` | rollouts produce nothing |
| `cycle_without_visit_budget` | on a cycle with `max_visits == 1`; the loop can't iterate |
| `join_k_exceeds_inbound` | join can never be satisfied |
| `no_input` | neither an entry node nor any inbound edge |

Mutation routinely produces transiently unhealthy graphs — `prune_edge` orphans
a node, `add_edge` creates a cycle whose nodes still have `max_visits == 1`. The
optimizer needs to *inspect and repair* those inside a generation, which an
exception makes impossible. Cycle and reachability analysis uses `networkx` via
`to_networkx()`; execution never touches it.

## Serialization and identity

`to_json()` / `from_json()` round trip losslessly, including the discriminated
condition union (verified by test). Beyond that, two content hashes:

- **`semantic_hash`** — nodes, edges, entry, outputs, budget, in canonical sorted
  order, excluding `id`, `name`, `lineage`, and `metadata`. Answers "have I
  already evaluated this exact behaviour?" Two independently discovered
  candidates that behave identically hash the same, which is what suppresses
  duplicates in a population and keys the response cache.
- **`structure_hash`** — node ids and roles, edge endpoints and condition kinds
  only. Answers "have I already explored this skeleton?", ignoring prompts,
  models, and decoding parameters. Lets the optimizer distinguish "this wiring is
  exhausted" from "this wiring needs better prompts", which is exactly the
  decision a reflective mutator has to make.

`clone()` deep-copies with a fresh `id` and is the base operation of every
mutator.

## Serialized form

```json
{
  "schema_version": "1.0",
  "id": "24a1f6e9d7d94546b4551d6c5895417d",
  "name": "verify_then_ship",
  "nodes": [
    {
      "id": "writer",
      "role_type": "worker",
      "model_id": "openai/gpt-4o",
      "instructions": "Draft the answer.",
      "prompt_strategy": "cot",
      "few_shot_examples": [],
      "temperature": 0.4,
      "context_budget": 6000,
      "max_output_tokens": 1024,
      "tool_access": [],
      "join": "all",
      "join_k": null,
      "merge": "concat",
      "fanout": 1,
      "max_visits": 1,
      "timeout_s": 120.0,
      "metadata": {}
    }
  ],
  "edges": [
    {
      "source": "writer",
      "target": "verifier",
      "label": "draft",
      "condition": {
        "kind": "predicate",
        "name": "min_length",
        "args": { "chars": 40 },
        "negate": false
      },
      "transform": { "kind": "raw", "field": null, "max_tokens": 1200 }
    }
  ],
  "entry": ["writer"],
  "outputs": ["verifier"],
  "budget": {
    "max_steps": 32,
    "max_total_tokens": 200000,
    "max_wall_clock_s": 300.0,
    "max_concurrency": 8,
    "max_usd": null
  },
  "lineage": { "parent_ids": [], "mutation": null, "generation": 0, "notes": null }
}
```

Every field is flat, enumerable, and JSON-native — no custom encoders — so a
candidate can be logged to JSONL, diffed in a PR, or shipped to a worker process
unchanged.

## What this buys Step 3

The mutators in your brief map onto this schema directly, and `lineage` records
which one produced each candidate so score deltas can be attributed:

| Mutator | Operation |
| --- | --- |
| `add_edge` / `prune_edge` | append to / remove from `edges`, then `diagnose()` and repair |
| `change_node_role` | set `role_type`, reset the scaffold-derived defaults |
| `split_node_into_parallel` | raise `fanout`, or clone the node and add a fan-in |
| `swap_model` | set `model_id` — the cheapest cost-axis move available |
| `rewrite_instructions` | the GEPA-style reflective edit; changes `semantic_hash`, leaves `structure_hash` fixed |
| `retune_decoding` | `temperature`, `context_budget`, `max_output_tokens` |

The one thing still missing is a `SearchSpace` object declaring the legal values
(model pool, allowed predicates, ranges). It belongs with the optimizer in
Step 3, because its contents depend on which mutators we implement.
