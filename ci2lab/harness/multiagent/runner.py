"""Subagent execution helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Callable

from ci2lab.console import console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.multiagent.roles import ROLE_SPECS, RoleSpec
from ci2lab.harness.multiagent.state import AgentRole, SubAgentResult
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.query.loop import run_agent
from ci2lab.harness.types import AgentConfig

TRACE_PREVIEW_CHARS = 600

ROLE_MAX_ROUNDS: dict[AgentRole, int] = {
    AgentRole.PLANNER: 5,
    AgentRole.RESEARCHER: 10,
    AgentRole.PYTHON_CODER: 15,
    AgentRole.FRONTEND_CODER: 15,
    AgentRole.TEST_CODER: 12,
    AgentRole.DOCS_CODER: 10,
    AgentRole.GENERALIST_CODER: 15,
    AgentRole.VALIDATOR: 8,
    AgentRole.REVIEWER: 6,
    AgentRole.SECURITY_REVIEWER: 6,
    # Peer-review lenses: enough rounds to read the manuscript and emit findings.
    AgentRole.INTAKE_REVIEWER: 10,
    AgentRole.SCOPE_REVIEWER: 8,
    AgentRole.NOVELTY_REVIEWER: 10,
    AgentRole.METHODOLOGY_REVIEWER: 8,
    AgentRole.FIELD_EXPERT_REVIEWER: 8,
    AgentRole.ADVERSARIAL_REVIEWER: 8,
    AgentRole.FORMAT_REVIEWER: 8,
    AgentRole.GROUNDEDNESS_VERIFIER: 6,
    AgentRole.REVISION_PLANNER: 6,
}


def _resolve_subagent_allowed_tools(
    role: AgentRole,
    config: AgentConfig,
) -> frozenset[str]:
    """Never let a subagent broaden an active skill allow-list."""
    role_allowed_tools = ROLE_SPECS[role].allowed_tools
    if config.skill_allowed_tools is None:
        return role_allowed_tools
    return frozenset(config.skill_allowed_tools & role_allowed_tools)


def build_role_anchor(role: AgentRole) -> str:
    """Build a short English role anchor for reinjection after tool rounds."""
    spec = ROLE_SPECS[role]
    return _role_anchor_from_spec(spec)


def _role_anchor_from_spec(spec: RoleSpec) -> str:
    return (
        f"Role anchor: You are currently acting as {spec.role.value}. "
        f"Your purpose in this phase is: {spec.phase_purpose} "
        f"Stay within this role. {spec.must_not} "
        "If blocked, report why instead of switching roles. "
        f"Expected output: {spec.expected_output}"
    )


def _allowed_tools_line(config: AgentConfig, spec: RoleSpec) -> str:
    """Concrete, comma-separated list of the tools this subagent may call.

    Prefer the effective allow-list on the config (it already folds in any
    parent skill restriction); fall back to the role's own set. Listing the
    real names — not just a yes/no — keeps weaker local models from reaching
    for a tool they were never granted, and counteracts the static fenced tool
    catalog, which advertises every tool regardless of role.
    """
    tools = config.skill_allowed_tools
    if tools is None:
        tools = spec.allowed_tools
    return ", ".join(sorted(tools)) if tools else "none (no tools — reason in prose only)"


def build_subagent_system_prompt(
    role: AgentRole,
    selection: ModelSelection,
    config: AgentConfig,
) -> str:
    """Build an isolated system prompt for a role-specific subagent."""
    spec = ROLE_SPECS[role]
    base_prompt = build_system_prompt(selection, config.cwd)
    allowed_tools_line = _allowed_tools_line(config, spec)
    # A read-only role has no way to hand a file to the next role, so it must be
    # told to return its findings as text instead of trying to persist them —
    # the failure mode where the researcher tried to write a scratch file the
    # downstream roles then could not find.
    if spec.can_write:
        write_directive = (
            "You CAN write files. Apply the change with your edit tools; do not "
            "merely describe it."
        )
    else:
        write_directive = (
            "You CANNOT write files — no write tool is available to you. Never "
            "attempt `write_file`/`edit_file`, and never plan to stash results in "
            "a scratch file for another role. The ONLY thing the next role "
            "receives is the text you return, so put every result, quote, and "
            "finding the rest of the run needs directly in your final response."
        )
    return (
        f"{base_prompt}\n\n"
        "## Subagent Role\n"
        f"- Role: {spec.role.value}\n"
        f"- Description: {spec.description}\n"
        f"- Can write files: {'yes' if spec.can_write else 'no'}\n"
        f"- Tools you may call: {allowed_tools_line}\n\n"
        "## Tool Boundary\n"
        f"{write_directive}\n"
        "Calling a tool outside the list above is not possible and will be "
        "rejected; stay within it.\n\n"
        "## Role Instructions\n"
        f"{spec.system_instructions}\n\n"
        "## Role Anchor\n"
        f"{_role_anchor_from_spec(spec)}\n\n"
        "You are running with an isolated subagent context. Use only the "
        "information provided in this task prompt and any context you gather "
        "with your allowed tools. If your role cannot complete the task with "
        "the provided context and allowed tools, stop and return `BLOCKED:` "
        "followed by the missing dependency or exact reason. Do not keep "
        "retrying the same action."
    )


def _preview_text(text: str, *, limit: int = TRACE_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "… (truncated)"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _read_jsonl(path: Path) -> list[dict]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception:  # noqa: BLE001
        return []


def _trace_status_from_run_summary(summary: dict | None) -> tuple[str, str | None]:
    if not summary:
        return "completed", None
    raw_status = str(summary.get("status") or "success")
    error = summary.get("error")
    low_error = str(error or "").lower()
    if raw_status == "success":
        return "completed", None
    if raw_status == "max_rounds":
        return "blocked", str(error or "Reached max rounds.")
    if raw_status == "interrupted":
        return "blocked", str(error or "Interrupted.")
    if "timeout" in low_error:
        return "timeout", str(error)
    return "failed", str(error) if error is not None else raw_status


def _load_subagent_run_artifacts(run_dir: str | None) -> dict[str, object]:
    if not run_dir:
        return {
            "status": "completed",
            "error": None,
            "duration_ms": None,
            "rounds": None,
            "tool_calls": [],
        }

    path = Path(run_dir)
    summary = _read_json(path / "run_summary.json")
    tool_entries = _read_jsonl(path / "tool_calls.jsonl")
    status, error = _trace_status_from_run_summary(summary)
    tool_calls = [
        {
            "tool": str(entry.get("tool", "")),
            "ok": bool(entry.get("ok", False)),
            "outcome": entry.get("outcome"),
            "arguments": entry.get("arguments") or {},
            "output_preview": _preview_text(str(entry.get("output", ""))),
            "error_preview": _preview_text(str(entry.get("error", "")))
            if entry.get("error")
            else None,
        }
        for entry in tool_entries
    ]
    duration_s = summary.get("duration_seconds") if summary else None
    return {
        "status": status,
        "error": error,
        "duration_ms": int(float(duration_s) * 1000) if duration_s is not None else None,
        "rounds": int(summary.get("rounds", 0)) if summary and summary.get("rounds") is not None else None,
        "tool_calls": tool_calls,
    }


def build_subagent_config(
    role: AgentRole,
    config: AgentConfig,
) -> AgentConfig:
    """Copy the parent config and apply role-specific tool restrictions."""
    role_max_rounds = min(config.max_rounds, ROLE_MAX_ROUNDS[role])
    return replace(
        config,
        max_rounds=role_max_rounds,
        stream=False,
        session_id=None,
        skill_allowed_tools=_resolve_subagent_allowed_tools(role, config),
        role_anchor=build_role_anchor(role),
        delegation_depth=config.delegation_depth + 1,
        verify_completion=False,
    )


def run_subagent(
    role: AgentRole,
    task_prompt: str,
    selection: ModelSelection,
    config: AgentConfig,
    *,
    attempt: int = 1,
    capture_output: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> SubAgentResult:
    """Execute one role-specific subagent with its own message context."""
    subagent_config = build_subagent_config(role, config)
    spec = ROLE_SPECS[role]
    system_prompt = build_subagent_system_prompt(role, selection, subagent_config)
    messages = [{"role": "system", "content": system_prompt}]

    # When a progress sink is attached we are running interactively (the REPL).
    # Show the subagent's full reasoning and tool calls instead of hiding them,
    # so the user can follow each role's thinking — and, crucially, knows what a
    # permission prompt is actually for. Headless runs keep output captured for
    # clean logs.
    show_output = on_progress is not None

    def show_progress(label: str) -> None:
        if on_progress:
            # A subagent finishing is not the end of the overall multi-agent
            # turn. Keep the transient indicator alive until the orchestrator
            # has produced the final combined answer.
            if label:
                on_progress(f"{role.value}: {label}")
            return
        # `console.capture()` intentionally hides verbose subagent output. A
        # plain flushed line bypasses that Rich capture so the interactive chat
        # still receives concise live activity updates.
        print(f"[multi-agent:{role.value}] {label}", flush=True)

    def _invoke() -> str:
        return run_agent(
            task_prompt,
            selection,
            config=subagent_config,
            messages=messages,
            on_progress=show_progress,
        )

    if show_output:
        # A clear banner so the scrolling reasoning/tool output below is
        # attributed to the right role.
        console.rule(f"[bold cyan]{role.value}[/bold cyan]")
        output = _invoke()
    elif capture_output:
        with console.capture():
            output = _invoke()
    else:
        output = _invoke()

    trace_data = _load_subagent_run_artifacts(subagent_config.last_run_dir)
    return SubAgentResult(
        role=role,
        task=task_prompt,
        output=output,
        status=str(trace_data["status"]),
        attempt=attempt,
        error=trace_data["error"],  # type: ignore[index]
        role_anchor=subagent_config.role_anchor,
        allowed_tools=sorted(subagent_config.skill_allowed_tools or ()),
        can_write=spec.can_write,
        input_prompt=_preview_text(task_prompt),
        subagent_run_dir=subagent_config.last_run_dir,
        tool_calls=list(trace_data["tool_calls"]),  # type: ignore[index]
        duration_ms=trace_data["duration_ms"],  # type: ignore[index]
        rounds=trace_data["rounds"],  # type: ignore[index]
    )
