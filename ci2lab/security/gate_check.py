"""Dry-run evaluation of the security gate (without executing tools)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import evaluate_tool_gate, normalize_security_engine
from ci2lab.security.opencode_config_io import (
    OpenCodeConfigBundle,
    load_opencode_config_bundle,
)
from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    parse_opencode_permissions,
)

_BASH_TOOLS = frozenset({"bash", "shell"})
_PATTERN_TOOLS = frozenset({"grep", "glob"})


def build_tool_args(tool: str, target: str) -> dict[str, Any]:
    """Build minimal arguments for evaluate_tool_gate."""
    name = tool.strip()
    if name in _BASH_TOOLS:
        return {"command": target}
    if name in _PATTERN_TOOLS:
        return {"path": ".", "pattern": target}
    return {"path": target}


def _gate_to_decision(gate: Any) -> str:
    if gate.blocked:
        return "deny"
    if gate.needs_confirm:
        return "ask"
    return "allow"


def load_permission_config(path: str | Path) -> OpenCodePermissionConfig:
    """Load permission from JSON (compat: delegates to opencode_config_io)."""
    return load_opencode_config_bundle(path).to_permission_config()


def evaluate_security_gate(
    *,
    engine: str | None = None,
    workspace: str,
    tool: str,
    target: str,
    permission_config: Mapping[str, Any] | OpenCodePermissionConfig | None = None,
    config_bundle: OpenCodeConfigBundle | None = None,
    auto_confirm: bool = False,
    security_profile: str = "standard",
    show_effective_config: bool = False,
) -> dict[str, Any]:
    """
    Evaluate the security gate without executing the tool.

    Raises ValueError if engine/tool are invalid.
    """
    normalized_engine = normalize_security_engine(engine)
    tool_name = tool.strip()
    if not tool_name:
        raise ValueError("tool cannot be empty.")

    opencode_perms: OpenCodePermissionConfig | None = None
    if config_bundle is not None:
        opencode_perms = config_bundle.to_permission_config()
    elif permission_config is not None:
        if isinstance(permission_config, OpenCodePermissionConfig):
            opencode_perms = permission_config
        else:
            opencode_perms = parse_opencode_permissions(dict(permission_config))

    config = AgentConfig(
        cwd=str(Path(workspace).resolve()),
        security_engine=normalized_engine,
        security_profile=security_profile,
        opencode_permissions=opencode_perms,
        auto_confirm=auto_confirm,
    )
    args = build_tool_args(tool_name, target)
    gate = evaluate_tool_gate(tool_name, args, config)
    result: dict[str, Any] = {
        "engine": normalized_engine,
        "tool": tool_name,
        "target": target,
        "decision": _gate_to_decision(gate),
        "reason": gate.reason,
        "matched_rule": gate.matched_rule,
        "external_directory": gate.external_directory,
        "hard_guards_enabled": gate.hard_guards_enabled,
        "experimental": gate.experimental,
        "blocked": gate.blocked,
        "needs_confirm": gate.needs_confirm,
    }
    if config_bundle is not None:
        result["config_source"] = config_bundle.config_source
        result["unsupported_tools"] = list(config_bundle.unsupported_tools)
        result["warnings"] = list(config_bundle.warnings)
        if show_effective_config and opencode_perms is not None:
            result["effective_permission"] = dict(opencode_perms.rules)
    return result
