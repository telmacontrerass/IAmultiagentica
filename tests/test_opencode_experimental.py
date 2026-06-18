"""OpenCode fidelity tests: config, aliases and dry gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci2lab.config import Ci2LabConfig, _apply_mapping
from ci2lab.harness.security_profiles import (
    SecurityConfig,
    merge_opencode_permission_sources,
    resolved_opencode_permissions,
)
from ci2lab.harness.types import AgentConfig
from ci2lab.security.comparison import export_comparison_report, run_comparison
from ci2lab.security.engine import evaluate_tool_gate
from ci2lab.security.gate_check import (
    build_tool_args,
    evaluate_security_gate,
    load_permission_config,
)
from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    evaluate_opencode_tool,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside\n", encoding="utf-8")
    return ws


def test_root_level_permission_works(workspace: Path):
    rules = resolved_opencode_permissions(
        SecurityConfig(engine="opencode_experimental"),
        root_permission={"edit": "deny"},
    )
    decision = evaluate_opencode_tool(
        "write_file",
        {"path": "new.txt", "content": "x"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "deny"
    assert decision.matched_rule == "edit:*"


def test_security_permission_overrides_root(workspace: Path):
    merged = merge_opencode_permission_sources(
        {"bash": {"*": "allow"}},
        {"bash": {"*": "ask"}},
    )
    rules = parse_rules(merged)
    decision = evaluate_opencode_tool(
        "bash",
        {"command": "echo hi"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "confirm"


def test_default_external_directory_is_deny(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    rules = OpenCodePermissionConfig.default_experimental()
    decision = evaluate_opencode_tool(
        "read_file",
        {"path": str(outside)},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "deny"
    assert decision.matched_rule == "external_directory:*"


def test_no_permission_uses_defaults(workspace: Path):
    rules = resolved_opencode_permissions(SecurityConfig())
    decision = evaluate_opencode_tool(
        "bash",
        {"command": "rm *"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "deny"


def parse_rules(merged: dict) -> OpenCodePermissionConfig:
    from ci2lab.security.opencode_permissions import parse_opencode_permissions

    return parse_opencode_permissions(merged)


def test_root_permission_does_not_affect_ci2lab(workspace: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="ci2lab",
        opencode_permissions=resolved_opencode_permissions(
            SecurityConfig(),
            root_permission={"read": "deny", "edit": "deny"},
        ),
    )
    gate = evaluate_tool_gate(
        "read_file",
        {"path": "inside.txt"},
        config,
    )
    assert not gate.blocked
    assert gate.needs_confirm is False


def test_permission_preset_opencode_dev(workspace: Path):
    rules = resolved_opencode_permissions(
        SecurityConfig(engine="opencode_experimental", permission_preset="opencode_dev")
    )
    decision = evaluate_opencode_tool(
        "write_file",
        {"path": "x.txt", "content": "a"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "confirm"


def test_permission_preset_external_allowed(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    rules = resolved_opencode_permissions(
        SecurityConfig(
            engine="opencode_experimental",
            permission_preset="opencode_external_allowed",
        )
    )
    decision = evaluate_opencode_tool(
        "read_file",
        {"path": str(outside)},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "allow"


def test_permission_preset_overridden_by_security_permission(workspace: Path):
    rules = resolved_opencode_permissions(
        SecurityConfig(
            engine="opencode_experimental",
            permission_preset="opencode_external_allowed",
            permission={"external_directory": {"*": "deny"}},
        )
    )
    outside = workspace.parent / "out.txt"
    outside.write_text("x\n", encoding="utf-8")
    decision = evaluate_opencode_tool(
        "read_file",
        {"path": str(outside)},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "deny"


def test_config_file_root_permission_parsed():
    base = Ci2LabConfig()
    updated = _apply_mapping(
        base,
        {
            "permission": {"edit": "ask"},
            "security": {"engine": "opencode_experimental"},
        },
    )
    assert updated.permission == {"edit": "ask"}
    perms = resolved_opencode_permissions(updated.security, root_permission=updated.permission)
    assert perms.rules["edit"] == "ask"


def test_edit_deny_blocks_write_file(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"edit": "deny"})
    d = evaluate_opencode_tool(
        "write_file",
        {"path": "x.txt", "content": "a"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "deny"


def test_edit_ask_affects_edit_file(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"edit": "ask"})
    d = evaluate_opencode_tool(
        "edit_file",
        {"path": "inside.txt", "old_string": "a", "new_string": "b"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "confirm"


def test_read_allow_affects_inspect_file(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"read": "allow"})
    d = evaluate_opencode_tool(
        "inspect_file",
        {"path": "inside.txt"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "allow"
    assert d.matched_rule == "read:*"


def test_read_deny_blocks_grep(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"read": "deny"})
    d = evaluate_opencode_tool(
        "grep",
        {"path": ".", "pattern": "inside"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "deny"


def test_read_deny_blocks_tree(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"read": "deny"})
    d = evaluate_opencode_tool(
        "tree",
        {"path": "."},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "deny"


def test_bash_git_allow_affects_shell(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"git *": "allow", "*": "ask"}})
    d = evaluate_opencode_tool(
        "shell",
        {"command": "git status"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "allow"
    assert d.matched_rule == "bash:git *"


def test_global_wildcard_only_when_no_tool_rule(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"*": "ask"})
    d = evaluate_opencode_tool(
        "bash",
        {"command": "echo x"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert d.action.value == "confirm"
    assert d.matched_rule == "*:*"


def test_export_comparison_creates_artifacts(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("x\n", encoding="utf-8")
    (workspace / ".env").write_text("S=1\n", encoding="utf-8")
    rows = run_comparison(workspace, outside_path=outside)
    result = export_comparison_report(rows, workspace=workspace, runs_dir="runs")
    assert result.csv_path.exists()
    assert result.markdown_path.exists()
    assert result.ci2lab_config_path.exists()
    assert result.opencode_config_path.exists()
    assert "# Security engine comparison" in result.markdown_path.read_text(encoding="utf-8")


def test_gate_check_evaluates_without_tool_dispatch(workspace: Path):
    """Dry gate: only evaluate_tool_gate, without registry.execute_tool."""
    result = evaluate_security_gate(
        engine="ci2lab",
        workspace=str(workspace),
        tool="read_file",
        target="inside.txt",
    )
    assert result["decision"] == "allow"
    assert result["blocked"] is False


def test_gate_check_json_output_fields(workspace: Path):
    result = evaluate_security_gate(
        engine="opencode_experimental",
        workspace=str(workspace),
        tool="bash",
        target="git status",
    )
    assert result["engine"] == "opencode_experimental"
    assert result["decision"] == "allow"
    assert result["matched_rule"] == "bash:git *"
    assert result["experimental"] is True
    assert result["hard_guards_enabled"] is False


def test_gate_check_external_path_ci2lab(workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    result = evaluate_security_gate(
        engine="ci2lab",
        workspace=str(workspace),
        tool="read_file",
        target=str(outside),
    )
    assert result["decision"] == "deny"
    assert result["hard_guards_enabled"] is True


def test_load_permission_config_root_level(tmp_path: Path):
    cfg = tmp_path / "perm.json"
    cfg.write_text(
        json.dumps({"permission": {"edit": "deny"}}),
        encoding="utf-8",
    )
    loaded = load_permission_config(cfg)
    assert loaded.rules["edit"] == "deny"


def test_build_tool_args_bash():
    assert build_tool_args("bash", "git status") == {"command": "git status"}


def test_build_tool_args_read():
    assert build_tool_args("read_file", "../x.txt") == {"path": "../x.txt"}
