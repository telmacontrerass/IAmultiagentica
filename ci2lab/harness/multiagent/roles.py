"""Role definitions for the sequential multi-agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field

from ci2lab.harness.multiagent.state import AgentRole


@dataclass(frozen=True)
class RoleSpec:
    """Static capabilities and instructions for one subagent role."""

    role: AgentRole
    description: str
    allowed_tools: frozenset[str]
    system_instructions: str
    phase_purpose: str
    must_not: str
    expected_output: str
    can_write: bool = False
    # Tools explicitly forbidden for this role (a subset of the harness tool
    # registry). The orchestrator uses this to detect and flag role violations
    # when the model attempts these tools even if the skill allowlist blocks them.
    forbidden_tools: frozenset[str] = field(default_factory=frozenset)


READ_TOOLS = frozenset({
    "ls",
    "glob",
    "read_file",
    "read_document",
    "grep",
})

EDIT_TOOLS = READ_TOOLS | frozenset({
    "edit_file",
    "write_file",
    "apply_patch",
})

RUNTIME_TOOLS = READ_TOOLS | frozenset({
    "bash",
})

REVIEW_TOOLS = READ_TOOLS | frozenset({
    "git_status",
    "git_diff",
})

VALIDATION_TOOLS = RUNTIME_TOOLS | frozenset({
    "git_status",
    "git_diff",
})


ROLE_SPECS: dict[AgentRole, RoleSpec] = {
    AgentRole.PLANNER: RoleSpec(
        role=AgentRole.PLANNER,
        description="Breaks the user request into ordered subtasks and success criteria.",
        allowed_tools=frozenset(),
        system_instructions=(
            "You are the planning subagent. Produce a concise implementation plan, "
            "identify dependencies, and state success criteria. Do not modify files."
        ),
        phase_purpose="Create a concise, safe implementation plan for the requested task.",
        must_not="Do not edit files, do not run validation, and do not claim implementation is complete.",
        expected_output="A short plan with ordered steps, relevant files or areas, dependencies, and success criteria.",
    ),
    AgentRole.RESEARCHER: RoleSpec(
        role=AgentRole.RESEARCHER,
        description="Inspects repository context and reports relevant files or constraints.",
        allowed_tools=READ_TOOLS,
        system_instructions=(
            "You are the research subagent. Inspect only the context needed for the "
            "task and summarize the files, APIs, and constraints found. Do not modify "
            "files. Do not claim to have created, verified, or modified any file — "
            "report only what your read tools confirm."
        ),
        phase_purpose="Gather evidence and inspect only the repository context needed for this task.",
        must_not=(
            "Do not implement changes, do not edit files, do not call write_file or "
            "apply_patch, and do not claim creation, verification, modification, or "
            "empty-diff unless a tool result proves it."
        ),
        expected_output="A focused summary of relevant files, APIs, constraints, and risks for the current task.",
        forbidden_tools=frozenset({"write_file", "edit_file", "apply_patch", "notebook_edit"}),
    ),
    AgentRole.PYTHON_CODER: RoleSpec(
        role=AgentRole.PYTHON_CODER,
        description="Implements Python backend or harness changes.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the Python implementation subagent. Apply focused Python changes "
            "that satisfy the plan and preserve existing behavior."
        ),
        phase_purpose="Implement the requested Python or harness change for this phase.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results or tests confirm it.",
        expected_output="A focused implementation with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.FRONTEND_CODER: RoleSpec(
        role=AgentRole.FRONTEND_CODER,
        description="Implements frontend UI, JavaScript, HTML, or CSS changes.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the frontend implementation subagent. Apply focused UI, HTML, "
            "CSS, or JavaScript changes that match the existing application style."
        ),
        phase_purpose="Implement the requested frontend change for this phase.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results or tests confirm it.",
        expected_output="A focused frontend implementation with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.TEST_CODER: RoleSpec(
        role=AgentRole.TEST_CODER,
        description="Adds or updates tests for the requested behavior.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the test implementation subagent. Add or update focused tests "
            "for the requested behavior without unrelated refactors."
        ),
        phase_purpose="Implement or update tests needed for the requested behavior.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results confirm the test changes.",
        expected_output="Focused test changes and concise evidence of what was added or updated.",
        can_write=True,
    ),
    AgentRole.DOCS_CODER: RoleSpec(
        role=AgentRole.DOCS_CODER,
        description="Updates documentation or examples.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the documentation subagent. Update docs or examples clearly "
            "and keep code behavior unchanged unless explicitly requested."
        ),
        phase_purpose="Implement the requested documentation or example update for this phase.",
        must_not="Do not switch to planning, validation, or review work, and do not change code behavior unless explicitly required.",
        expected_output="Focused documentation or example updates with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.GENERALIST_CODER: RoleSpec(
        role=AgentRole.GENERALIST_CODER,
        description="Implements changes that do not fit a narrower coder role.",
        allowed_tools=EDIT_TOOLS,
        system_instructions=(
            "You are the general implementation subagent. Make the smallest coherent "
            "change that satisfies the task and preserves existing behavior."
        ),
        phase_purpose="Implement the requested change for this phase with the smallest coherent edit.",
        must_not="Do not switch to planning, validation, or review work, and do not claim success before tool results or tests confirm it.",
        expected_output="A focused implementation with concise evidence of what changed.",
        can_write=True,
    ),
    AgentRole.VALIDATOR: RoleSpec(
        role=AgentRole.VALIDATOR,
        description="Runs validation and reports pass/fail evidence.",
        allowed_tools=VALIDATION_TOOLS,
        system_instructions=(
            "You are the validation subagent. Run or recommend focused checks, report "
            "whether validation passed, and include actionable failure details. "
            "Do NOT call `todo_write`, `write_file`, `edit_file`, `apply_patch`, or "
            "`notebook_edit` — these are forbidden for this role and will be recorded "
            "as a role violation. Your expected tool sequence is: `read_file`/`glob` "
            "to inspect changes, `bash` to run tests, `git_status`/`git_diff` for "
            "scope, then a verdict."
        ),
        phase_purpose="Validate the current result using tests or deterministic checks.",
        must_not=(
            "Do not implement changes, do not rewrite the plan, do not hide failures, "
            "and do NOT use `todo_write`, `write_file`, `edit_file`, or `apply_patch`. "
            "Do not plan tasks with todo tools — execute checks and emit a verdict."
        ),
        expected_output="A clear validation result that states pass or fail and includes actionable failure details when needed.",
        forbidden_tools=frozenset({
            "todo_write",
            "write_file", "edit_file", "apply_patch", "notebook_edit",
        }),
    ),
    AgentRole.REVIEWER: RoleSpec(
        role=AgentRole.REVIEWER,
        description="Reviews the final result for regressions and completeness.",
        allowed_tools=REVIEW_TOOLS,
        system_instructions=(
            "You are the review subagent. Review the completed work for bugs, "
            "missing tests, regressions, and incomplete requirements. Do not modify files. "
            "Do NOT call `todo_write`, `write_file`, `edit_file`, or `apply_patch` — "
            "these are forbidden for this role. Your review must be grounded only in "
            "the task, the run evidence, and your `git_status`/`git_diff` tool results. "
            "Do not invent file names, tool names, or artifacts that are not present in "
            "the task or real tool-call evidence."
        ),
        phase_purpose="Review the completed result for bugs, regressions, gaps, and incomplete requirements.",
        must_not=(
            "Do not implement changes, do not edit files, do not use `todo_write`, "
            "`write_file`, `edit_file`, or `apply_patch`, do not claim validation work "
            "you did not perform, and do not mention files or tools unrelated to the task."
        ),
        expected_output="A concise review with concrete findings, risks, and missing coverage if any.",
        forbidden_tools=frozenset({
            "todo_write",
            "write_file", "edit_file", "apply_patch", "notebook_edit",
        }),
    ),
    AgentRole.SECURITY_REVIEWER: RoleSpec(
        role=AgentRole.SECURITY_REVIEWER,
        description="Reviews permission, command, and security-sensitive changes.",
        allowed_tools=REVIEW_TOOLS,
        system_instructions=(
            "You are the security review subagent. Check for permission, command "
            "execution, secret-handling, and filesystem safety risks. Do not modify files. "
            "Do NOT call `todo_write`, `write_file`, `edit_file`, or `apply_patch` — "
            "these are forbidden for this role. Your review must be grounded only in "
            "the task, the run evidence, and your `git_status`/`git_diff` tool results. "
            "Do not invent file names, tool names, or artifacts that are not present in "
            "the task or real tool-call evidence."
        ),
        phase_purpose="Look for security risks, permission expansion, leaks, bypasses, or unsafe tool use.",
        must_not=(
            "Do not implement changes, do not edit files, do not use `todo_write`, "
            "`write_file`, `edit_file`, or `apply_patch`, and do not ignore potential "
            "security or permission regressions. Do not mention tools or files not "
            "present in the task or real tool-call evidence."
        ),
        expected_output="A concise security review with concrete risks, permission concerns, and unsafe behaviors if found.",
        forbidden_tools=frozenset({
            "todo_write",
            "write_file", "edit_file", "apply_patch", "notebook_edit",
        }),
    ),
}
