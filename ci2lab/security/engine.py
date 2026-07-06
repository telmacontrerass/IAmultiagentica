"""Security engine selection: CI2Lab, OpenCode experimental, Claude experimental."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.decisions import DecisionAction
from ci2lab.security.policy import check_command_allowed, check_path_allowed

_PATH_ARG_TOOLS = frozenset(
    {
        "read_file",
        "read_document",
        "create_quiz_questions",
        "ls",
        "glob",
        "grep",
        "write_file",
        "edit_file",
        "write_docx",
        "write_pptx",
        "file_info",
        "tree",
        "inspect_file",
        "extract_visual_document",
    }
)

_WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "write_docx",
        "write_pptx",
        "apply_patch",
        "fill_docx_template",
        "docx_to_pdf",
        "pdf_to_docx",
    }
)
_CONFIRM_TOOLS = frozenset({"bash", *_WRITE_TOOLS})

CLAUDE_EXTERNAL_ALLOW_IGNORED = (
    "external_directory=allow ignored by claude_experimental hard workspace policy"
)


def _path_arg(tool_name: str, args: dict[str, Any]) -> str | None:
    """Return the path argument that represents a tool's filesystem target."""
    if tool_name == "write_pptx":
        value = args.get("output_path")
    else:
        value = args.get("path")
    if value is None:
        return None
    return str(value)


class SecurityEngineName(str, Enum):
    """Canonical names of the available security engines.

    Attributes:
        CI2LAB: Default sandbox-first engine with hard guards.
        STANDARD: Alias of :attr:`CI2LAB`.
        OPENCODE_EXPERIMENTAL: Permission-layer engine without hard guards.
        CLAUDE_EXPERIMENTAL: Permission-layer engine with hard guards.
    """

    CI2LAB = "ci2lab"
    STANDARD = "standard"  # alias of ci2lab
    OPENCODE_EXPERIMENTAL = "opencode_experimental"
    CLAUDE_EXPERIMENTAL = "claude_experimental"


DEFAULT_SECURITY_ENGINE = SecurityEngineName.CLAUDE_EXPERIMENTAL.value

CLI_SECURITY_ENGINE_CHOICES = (
    SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    SecurityEngineName.CI2LAB.value,
    SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
)

_ENGINE_ALIASES = {
    "ci2lab": SecurityEngineName.CI2LAB.value,
    "standard": SecurityEngineName.CI2LAB.value,
    "opencode_experimental": SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
    "opencode": SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
    "claude_experimental": SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    "claude": SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
}

_PERMISSION_LAYER_ENGINES = frozenset(
    {
        SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
        SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    }
)


class UnknownSecurityEngineError(ValueError):
    """Raised when a security engine name is not recognized."""


def normalize_security_engine(raw: str | None) -> str:
    """Normalize a raw engine name (or alias) to its canonical value.

    Args:
        raw: User-provided engine name or alias; may be None or empty.

    Returns:
        The canonical engine name, or :data:`DEFAULT_SECURITY_ENGINE` when
        ``raw`` is falsy.

    Raises:
        UnknownSecurityEngineError: If ``raw`` is a non-empty unknown name.
    """
    if not raw:
        return DEFAULT_SECURITY_ENGINE
    key = raw.strip().lower()
    if key not in _ENGINE_ALIASES:
        valid = ", ".join(
            sorted(
                {
                    SecurityEngineName.CI2LAB.value,
                    SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
                    SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
                }
            )
        )
        raise UnknownSecurityEngineError(
            f"Unknown security engine: {raw!r}. Valid values: {valid}."
        )
    return _ENGINE_ALIASES[key]


def uses_permission_layer(security_engine: str) -> bool:
    """Return whether the engine runs the OpenCode-style permission layer.

    Args:
        security_engine: Engine name or alias.

    Returns:
        True for the opencode/claude experimental engines, else False.
    """
    return normalize_security_engine(security_engine) in _PERMISSION_LAYER_ENGINES


def enforce_ci2lab_hard_policy(security_engine: str) -> bool:
    """Return whether the engine enforces CI2Lab hard guards.

    Hard guards cover workspace confinement, the secret-file policy and the
    bash command blocklist.

    Args:
        security_engine: Engine name or alias.

    Returns:
        True for the ci2lab and claude_experimental engines, else False.
    """
    engine = normalize_security_engine(security_engine)
    return engine in {
        SecurityEngineName.CI2LAB.value,
        SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    }


def is_experimental_engine(security_engine: str) -> bool:
    """Return whether the engine is one of the experimental engines.

    Args:
        security_engine: Engine name or alias.

    Returns:
        True for the opencode/claude experimental engines, else False.
    """
    engine = normalize_security_engine(security_engine)
    return engine in {
        SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
        SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    }


@dataclass(frozen=True)
class ToolGateResult:
    """Result of the security gate evaluated before executing a tool.

    Attributes:
        proceed: True if the tool is allowed to run (possibly after confirm).
        blocked: True if the tool was hard-blocked or denied.
        message: Human-readable message, typically for blocks.
        outcome: Outcome label recorded in the audit log.
        needs_confirm: True if the tool requires user confirmation first.
        reason: Machine-readable reason code for the decision.
        engine: Canonical name of the engine that produced the result.
        matched_rule: Identifier of the rule that produced the decision.
        external_directory: True if the target lies outside the workspace.
        hard_guards_enabled: True if hard guards were applied.
        permission_layer_enabled: True if the permission layer was applied.
        experimental: True if produced by an experimental engine.
        session_approval_used: True if a cached session approval was applied.
        session_approval_scope: Scope of the session approval, if used.
        risk_note: Optional advisory note about a security risk.
    """

    proceed: bool
    blocked: bool = False
    message: str | None = None
    outcome: str | None = None
    needs_confirm: bool = False
    reason: str = ""
    engine: str = DEFAULT_SECURITY_ENGINE
    matched_rule: str | None = None
    external_directory: bool = False
    hard_guards_enabled: bool = True
    permission_layer_enabled: bool = False
    experimental: bool = False
    session_approval_used: bool = False
    session_approval_scope: str | None = None
    risk_note: str | None = None


def _run_hard_guards(
    tool_name: str,
    args: dict[str, Any],
    config: AgentConfig,
    *,
    engine: str,
    experimental: bool,
) -> ToolGateResult | None:
    """CI2Lab hard layer. Returns ToolGateResult if it blocks; None if it passes."""
    from ci2lab.harness.security_profiles import (
        SECURITY_PROFILE_BLOCKED_OUTCOME,
        is_tool_blocked_by_profile,
        profile_block_message,
    )

    profile = config.security_profile

    if is_tool_blocked_by_profile(profile, tool_name):
        return ToolGateResult(
            proceed=False,
            blocked=True,
            message=profile_block_message(tool_name, profile),
            outcome=SECURITY_PROFILE_BLOCKED_OUTCOME,
            reason="security_profile",
            engine=engine,
            matched_rule="hard:security_profile",
            hard_guards_enabled=True,
            permission_layer_enabled=False,
            experimental=experimental,
        )

    path_arg = _path_arg(tool_name, args)
    if tool_name in _PATH_ARG_TOOLS and path_arg is not None:
        path_decision = check_path_allowed(config.cwd, path_arg)
        if path_decision.action is DecisionAction.DENY:
            external = path_decision.reason == "outside_workspace"
            matched = "hard:outside_workspace" if external else "hard:secret_file"
            risk = (
                CLAUDE_EXTERNAL_ALLOW_IGNORED
                if engine == SecurityEngineName.CLAUDE_EXPERIMENTAL.value and external
                else None
            )
            return ToolGateResult(
                proceed=False,
                blocked=True,
                message=path_decision.message
                if (path_decision.message or "").startswith("Error:")
                else f"Error: {path_decision.message}",
                outcome=path_decision.outcome,
                reason=path_decision.reason,
                engine=engine,
                matched_rule=matched,
                external_directory=external,
                hard_guards_enabled=True,
                permission_layer_enabled=False,
                experimental=experimental,
                risk_note=risk,
            )

    if tool_name == "bash":
        cmd = str(args.get("command", ""))
        cmd_decision = check_command_allowed(cmd, config.cwd, security_profile=profile)
        if cmd_decision.action is DecisionAction.DENY:
            return ToolGateResult(
                proceed=False,
                blocked=True,
                message=cmd_decision.message,
                outcome=cmd_decision.outcome,
                reason=cmd_decision.reason,
                engine=engine,
                matched_rule="hard:bash_blocklist",
                hard_guards_enabled=True,
                permission_layer_enabled=False,
                experimental=experimental,
            )

    return None


def _permission_layer_gate(
    tool_name: str,
    args: dict[str, Any],
    config: AgentConfig,
    *,
    engine: str,
    hard_guards_enabled: bool,
) -> ToolGateResult:
    """Evaluate the OpenCode-style permission layer for a tool call.

    Resolves allow/ask/deny rules and applies any cached session approvals.

    Args:
        tool_name: Name of the tool being evaluated.
        args: Arguments passed to the tool.
        config: Active agent configuration.
        engine: Canonical engine name driving this evaluation.
        hard_guards_enabled: Whether hard guards already ran for this engine.

    Returns:
        The :class:`ToolGateResult` produced by the permission layer.
    """
    from ci2lab.security.opencode_permissions import (
        OpenCodePermissionConfig,
        evaluate_opencode_tool,
    )

    rules = config.opencode_permissions or OpenCodePermissionConfig.default_experimental()
    decision = evaluate_opencode_tool(
        tool_name,
        args,
        workspace=config.cwd,
        rules=rules,
        auto_confirm=config.auto_confirm,
    )

    risk_note: str | None = None
    if (
        engine == SecurityEngineName.CLAUDE_EXPERIMENTAL.value
        and decision.external_directory
        and not hard_guards_enabled
    ):
        risk_note = CLAUDE_EXTERNAL_ALLOW_IGNORED

    if decision.action is DecisionAction.DENY:
        return ToolGateResult(
            proceed=False,
            blocked=True,
            message=decision.message or f"Error: permission denied ({decision.reason})",
            outcome="blocked_by_permission",
            reason=decision.reason,
            engine=engine,
            matched_rule=decision.matched_rule,
            external_directory=decision.external_directory,
            hard_guards_enabled=hard_guards_enabled,
            permission_layer_enabled=True,
            experimental=True,
            risk_note=risk_note,
        )

    needs_confirm = decision.action is DecisionAction.CONFIRM
    if needs_confirm and not config.auto_confirm:
        from ci2lab.security.audit import get_audit_persist_context
        from ci2lab.security.session_permissions import (
            build_approval_fingerprint,
            consume_session_approval,
            lookup_session_approval,
            resolve_session_key,
        )

        audit_ctx = get_audit_persist_context()
        session_key = resolve_session_key(
            session_id=config.approval_session_id or config.session_id,
            run_id=(audit_ctx.run_id if audit_ctx else None),
        )
        fingerprint = build_approval_fingerprint(
            engine=engine,
            tool_name=tool_name,
            args=args,
            matched_rule=decision.matched_rule,
            external_directory=decision.external_directory,
        )
        approval = lookup_session_approval(session_key, fingerprint)
        if approval == "deny_once":
            consume_session_approval(session_key, fingerprint, "deny_once")
            return ToolGateResult(
                proceed=False,
                blocked=True,
                message="Error: denied by session approval (deny_once)",
                outcome="denied",
                reason="session_deny_once",
                engine=engine,
                matched_rule=decision.matched_rule,
                external_directory=decision.external_directory,
                hard_guards_enabled=hard_guards_enabled,
                permission_layer_enabled=True,
                experimental=True,
                session_approval_used=True,
                session_approval_scope="deny_once",
            )
        if approval in {"allow_session", "allow_once"}:
            if approval == "allow_once":
                consume_session_approval(session_key, fingerprint, "allow_once")
            return ToolGateResult(
                proceed=True,
                needs_confirm=False,
                reason="session_allow",
                engine=engine,
                matched_rule=decision.matched_rule,
                external_directory=decision.external_directory,
                hard_guards_enabled=hard_guards_enabled,
                permission_layer_enabled=True,
                experimental=True,
                session_approval_used=True,
                session_approval_scope=approval,
            )

    return ToolGateResult(
        proceed=True,
        needs_confirm=needs_confirm and not config.auto_confirm,
        reason=decision.reason,
        engine=engine,
        matched_rule=decision.matched_rule,
        external_directory=decision.external_directory,
        hard_guards_enabled=hard_guards_enabled,
        permission_layer_enabled=True,
        experimental=True,
        risk_note=risk_note,
    )


def _ci2lab_gate(
    tool_name: str,
    args: dict[str, Any],
    config: AgentConfig,
) -> ToolGateResult:
    """Evaluate the gate for the default ci2lab (sandbox-first) engine."""
    hard = _run_hard_guards(
        tool_name,
        args,
        config,
        engine=SecurityEngineName.CI2LAB.value,
        experimental=False,
    )
    if hard is not None:
        return hard

    needs_confirm = tool_name in _CONFIRM_TOOLS
    return ToolGateResult(
        proceed=True,
        needs_confirm=needs_confirm,
        reason="ci2lab_hard_policy_passed",
        engine=SecurityEngineName.CI2LAB.value,
        matched_rule="hard:passed",
        hard_guards_enabled=True,
        permission_layer_enabled=False,
        experimental=False,
    )


def _opencode_gate(
    tool_name: str,
    args: dict[str, Any],
    config: AgentConfig,
) -> ToolGateResult:
    """Evaluate the gate for the opencode_experimental engine (no hard guards)."""
    return _permission_layer_gate(
        tool_name,
        args,
        config,
        engine=SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
        hard_guards_enabled=False,
    )


def _claude_experimental_gate(
    tool_name: str,
    args: dict[str, Any],
    config: AgentConfig,
) -> ToolGateResult:
    """Evaluate the gate for claude_experimental: hard guards then permissions."""
    hard = _run_hard_guards(
        tool_name,
        args,
        config,
        engine=SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
        experimental=True,
    )
    if hard is not None:
        return hard

    return _permission_layer_gate(
        tool_name,
        args,
        config,
        engine=SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
        hard_guards_enabled=True,
    )


def evaluate_tool_gate(
    tool_name: str,
    args: dict[str, Any],
    config: AgentConfig,
) -> ToolGateResult:
    """Evaluate a tool call against the engine selected in ``config``.

    Dispatches to the ci2lab, opencode_experimental or claude_experimental
    gate based on ``config.security_engine``.

    Args:
        tool_name: Name of the tool being evaluated.
        args: Arguments passed to the tool.
        config: Active agent configuration (selects the engine).

    Returns:
        The :class:`ToolGateResult` describing whether the tool may run.
    """
    engine = normalize_security_engine(config.security_engine)
    if engine == SecurityEngineName.OPENCODE_EXPERIMENTAL.value:
        return _opencode_gate(tool_name, args, config)
    if engine == SecurityEngineName.CLAUDE_EXPERIMENTAL.value:
        return _claude_experimental_gate(tool_name, args, config)
    return _ci2lab_gate(tool_name, args, config)
