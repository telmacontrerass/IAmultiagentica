"""The `delegate` tool: run a focused subtask in an isolated subagent context.

The main agent hands a self-contained subtask to a fresh subagent that has its
own message history and only sees the task prompt — not the whole conversation.
Only the subagent's final result returns to the main loop. This is the core
defense against "getting lost" on long tasks: heavy exploration or a contained
implementation step happens off to the side and never bloats the main context.

Two modes keep it simple for weaker local models:
  - "explore" -> a read-only research subagent (no file writes).
  - "edit"    -> an implementation subagent that may write files.

Recursion is bounded by `AgentConfig.delegation_depth`: a delegated subagent is
built with role-restricted tools that never include `delegate`, and the depth
guard refuses a second level even if a skill allow-list were to expose it.
"""

from __future__ import annotations

from dataclasses import replace

from ci2lab.harness.token_usage import TokenUsageState
from ci2lab.harness.types import AgentConfig

# Top-level agent is depth 0; a single level of delegation (depth 1) is allowed.
# Deeper nesting tends to amplify weak-model errors and burn rounds, so stop there.
MAX_DELEGATION_DEPTH = 1

_MODE_ROLES = {
    "explore": "RESEARCHER",
    "research": "RESEARCHER",
    "read": "RESEARCHER",
    "edit": "GENERALIST_CODER",
    "code": "GENERALIST_CODER",
    "implement": "GENERALIST_CODER",
}


def run_delegation(config: AgentConfig, task: str, mode: str = "explore") -> str:
    """Run `task` in an isolated subagent and return only its final result."""
    task = (task or "").strip()
    if not task:
        return "Error: delegate requires a non-empty `task` describing the subtask."

    if config.delegation_depth >= MAX_DELEGATION_DEPTH:
        return (
            "Error: delegation is not available inside a delegated subagent "
            "(max depth reached). Do this step yourself with the normal tools."
        )

    selection = config.selection
    if selection is None:
        return (
            "Error: delegation is unavailable in this run (no model selection "
            "bound). Do this step yourself with the normal tools."
        )

    # Lazy import: runner -> loop -> tools.registry would otherwise import-cycle.
    from ci2lab.harness.multiagent.runner import run_subagent
    from ci2lab.harness.multiagent.state import AgentRole

    role_name = _MODE_ROLES.get((mode or "explore").strip().lower())
    if role_name is None:
        return (
            f"Error: unknown delegate mode '{mode}'. Use 'explore' (read-only "
            "research) or 'edit' (may write files)."
        )
    role = AgentRole[role_name]

    # Isolate token accounting so the subagent's usage does not reset or pollute
    # the parent turn's counters (run_agent resets the turn on entry).
    parent_for_sub = replace(config, token_usage=TokenUsageState())

    result = run_subagent(
        role,
        task,
        selection,
        parent_for_sub,
        capture_output=False,
    )

    output = (result.output or "").strip()
    if result.status == "completed":
        return output or "(the delegated subagent returned no output)"

    detail = (result.error or result.status or "did not finish").strip()
    return (
        f"Error: the delegated subagent did not complete ({result.status}): "
        f"{detail}.\nPartial result:\n{output or '(none)'}"
    )
