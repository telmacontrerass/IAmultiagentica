"""Selección de motor de seguridad: CI2Lab, OpenCode experimental, Claude experimental."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.decisions import DecisionAction
from ci2lab.security.policy import check_command_allowed, check_path_allowed

_PATH_ARG_TOOLS = frozenset({
    "read_file",
    "read_document",
    "ls",
    "glob",
    "grep",
    "write_file",
    "edit_file",
    "write_docx",
    "file_info",
    "tree",
    "inspect_file",
})

_WRITE_TOOLS = frozenset(
    {"write_file", "edit_file", "write_docx", "apply_patch", "fill_docx_template"}
)
_CONFIRM_TOOLS = frozenset({"bash", *_WRITE_TOOLS})

CLAUDE_EXTERNAL_ALLOW_IGNORED = (
    "external_directory=allow ignored by claude_experimental hard workspace policy"
)


class SecurityEngineName(str, Enum):
    CI2LAB = "ci2lab"
    STANDARD = "standard"  # alias de ci2lab
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

_PERMISSION_LAYER_ENGINES = frozenset({
    SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
    SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
})


class UnknownSecurityEngineError(ValueError):
    """Motor de seguridad no reconocido."""


def normalize_security_engine(raw: str | None) -> str:
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
            f"Motor de seguridad desconocido: {raw!r}. Valores validos: {valid}."
        )
    return _ENGINE_ALIASES[key]


def uses_permission_layer(security_engine: str) -> bool:
    return normalize_security_engine(security_engine) in _PERMISSION_LAYER_ENGINES


def enforce_ci2lab_hard_policy(security_engine: str) -> bool:
    """Hard policy en ejecución de tools (workspace, secretos, blocklist)."""
    engine = normalize_security_engine(security_engine)
    return engine in {
        SecurityEngineName.CI2LAB.value,
        SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    }


def is_experimental_engine(security_engine: str) -> bool:
    engine = normalize_security_engine(security_engine)
    return engine in {
        SecurityEngineName.OPENCODE_EXPERIMENTAL.value,
        SecurityEngineName.CLAUDE_EXPERIMENTAL.value,
    }


@dataclass(frozen=True)
class ToolGateResult:
    """Resultado de la puerta de seguridad antes de ejecutar una tool."""

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
    """Capa dura CI2Lab. Devuelve ToolGateResult si bloquea; None si pasa."""
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

    if tool_name in _PATH_ARG_TOOLS and "path" in args:
        path_decision = check_path_allowed(config.cwd, str(args["path"]))
        if path_decision.action is DecisionAction.DENY:
            external = path_decision.reason == "outside_workspace"
            matched = (
                "hard:outside_workspace"
                if external
                else "hard:secret_file"
            )
            risk = (
                CLAUDE_EXTERNAL_ALLOW_IGNORED
                if engine == SecurityEngineName.CLAUDE_EXPERIMENTAL.value
                and external
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
        cmd_decision = check_command_allowed(
            cmd, config.cwd, security_profile=profile
        )
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
            message=decision.message or f"Error: permiso denegado ({decision.reason})",
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

        session_key = resolve_session_key(
            session_id=config.session_id,
            run_id=(
                get_audit_persist_context().run_id
                if get_audit_persist_context()
                else None
            ),
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
                message="Error: denegado por aprobación de sesión (deny_once)",
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
    engine = normalize_security_engine(config.security_engine)
    if engine == SecurityEngineName.OPENCODE_EXPERIMENTAL.value:
        return _opencode_gate(tool_name, args, config)
    if engine == SecurityEngineName.CLAUDE_EXPERIMENTAL.value:
        return _claude_experimental_gate(tool_name, args, config)
    return _ci2lab_gate(tool_name, args, config)
