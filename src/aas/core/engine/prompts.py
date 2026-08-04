"""Turning a node plus its inbox into a concrete model request.

Prompt assembly is kept out of the scheduler because it is itself part of the
search space: the role preamble and strategy scaffold below are the *defaults* a
freshly mutated node inherits, and a reflective optimizer overrides them by
editing `AgentNode.instructions`.

Context assembly is where token cost is won or lost, so this module owns
`context_budget` enforcement and reports truncation as an observable event.
"""

from __future__ import annotations

from collections import Counter

from aas.core.graph.schema import AgentNode, MergePolicy, PromptStrategy, RoleType

from .trace import Activation, Message

ROLE_PREAMBLE: dict[RoleType, str] = {
    RoleType.ORCHESTRATOR: (
        "You coordinate a team of agents. Decompose the task and issue precise, "
        "self-contained instructions."
    ),
    RoleType.WORKER: "You execute the task you are given and return the result.",
    RoleType.PARALLEL_WORKER: (
        "You produce one independent attempt at the task. Do not assume other "
        "attempts exist."
    ),
    RoleType.VERIFIER: (
        "You check the candidate answer against the task requirements. State "
        "PASS or FAIL first, then the reason."
    ),
    RoleType.CRITIC: (
        "You find the weakest part of the candidate answer and say concretely "
        "how to improve it. Do not rewrite it yourself."
    ),
}

STRATEGY_SCAFFOLD: dict[PromptStrategy, str] = {
    PromptStrategy.DIRECT: "Answer directly, with no preamble.",
    PromptStrategy.COT: "Think step by step, then give the final answer after 'ANSWER:'.",
    PromptStrategy.REACT: (
        "Work in Thought/Action/Observation cycles. Emit one Action at a time as "
        "`Action: tool_name(arguments)`. Finish with 'ANSWER:'."
    ),
    PromptStrategy.FEW_SHOT: "Follow the pattern of the worked examples exactly.",
}


def merge_inbox(activations: list[Activation], policy: MergePolicy) -> list[Activation]:
    """Fold several inbound payloads into the set that will enter the prompt."""
    if not activations:
        return []
    if policy is MergePolicy.FIRST:
        return activations[:1]
    if policy is MergePolicy.MAJORITY_VOTE:
        counts = Counter(a.content.strip() for a in activations)
        winner, _ = counts.most_common(1)[0]
        return [a for a in activations if a.content.strip() == winner][:1]
    return activations


class DefaultPromptCompiler:
    """Assembles `[system, user]` messages and enforces the node's context budget.

    Single-shot by design: it emits the ReAct scaffold but does not run the
    tool loop. Driving tool cycles is a `NodeRunner` concern, so a `ReactNodeRunner`
    can be introduced without changing prompt assembly.
    """

    def __init__(self, count_tokens) -> None:
        self._count = count_tokens

    def compile(
        self, node: AgentNode, inbox: list[Activation], task_input: str
    ) -> tuple[list[Message], bool]:
        system = self._system_prompt(node)
        merged = merge_inbox(inbox, node.merge)

        model = node.model_id
        overhead = self._count(system, model) + self._count(task_input, model)
        remaining = max(0, node.context_budget - overhead)
        share = remaining // max(1, len(merged)) if merged else 0

        truncated = False
        sections: list[str] = [f"# Task\n{task_input}"]
        for activation in merged:
            body, was_cut = self._fit(activation.content, share, model)
            truncated = truncated or was_cut
            heading = activation.label or activation.source_node or "input"
            sections.append(f"# From: {heading}\n{body}")

        return [
            Message(role="system", content=system),
            Message(role="user", content="\n\n".join(sections)),
        ], truncated

    def _system_prompt(self, node: AgentNode) -> str:
        parts = [ROLE_PREAMBLE[node.role_type], STRATEGY_SCAFFOLD[node.prompt_strategy]]
        if node.instructions:
            parts.append(node.instructions)
        if node.tool_access:
            parts.append("Available tools: " + ", ".join(node.tool_access))
        if node.prompt_strategy is PromptStrategy.FEW_SHOT and node.few_shot_examples:
            examples = "\n\n".join(
                f"Input: {e.input}\nOutput: {e.output}" for e in node.few_shot_examples
            )
            parts.append(f"Worked examples:\n{examples}")
        return "\n\n".join(parts)

    def _fit(self, text: str, max_tokens: int, model_id: str) -> tuple[str, bool]:
        if max_tokens <= 0:
            return "", bool(text)
        if self._count(text, model_id) <= max_tokens:
            return text, False
        ratio = max_tokens / max(1, self._count(text, model_id))
        trimmed = text[: max(1, int(len(text) * ratio))]
        while trimmed and self._count(trimmed, model_id) > max_tokens:
            trimmed = trimmed[: int(len(trimmed) * 0.9)]
        return trimmed + "\n[...truncated to fit context_budget]", True
