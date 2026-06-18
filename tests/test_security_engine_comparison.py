"""Tests for the JSONL audit log and the security-engine comparator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.audit import (
    AuditPersistContext,
    clear_audit_log,
    get_audit_persist_context,
    resolve_audit_path_within_workspace,
    set_audit_persist_context,
)
from ci2lab.security.comparison import run_comparison
from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    evaluate_opencode_tool,
    _match_best_rule,
    _resolve_tool_permission,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside\n", encoding="utf-8")
    (ws / ".env").write_text("SECRET=1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-data\n", encoding="utf-8")
    return ws


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    return (tmp_path / "outside" / "secret.txt").resolve()


@pytest.fixture(autouse=True)
def _reset_audit():
    clear_audit_log()
    set_audit_persist_context(None)
    yield
    clear_audit_log()
    set_audit_persist_context(None)


def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_audit_jsonl_created_in_workspace(workspace: Path, outside_secret: Path):
    set_audit_persist_context(AuditPersistContext(workspace=str(workspace)))
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(cwd=str(workspace), security_engine="ci2lab"),
    )
    path = resolve_audit_path_within_workspace(str(workspace))
    assert path.exists()
    assert path.is_relative_to(workspace.resolve())


def test_audit_jsonl_contains_allow(workspace: Path):
    set_audit_persist_context(AuditPersistContext(workspace=str(workspace)))
    execute_tool(
        ToolCall("read_file", {"path": "inside.txt"}, "t1"),
        AgentConfig(cwd=str(workspace), security_engine="ci2lab", auto_confirm=True),
    )
    records = _read_jsonl(resolve_audit_path_within_workspace(str(workspace)))
    assert any(r["decision"] == "allow" for r in records)


def test_audit_jsonl_contains_deny(workspace: Path, outside_secret: Path):
    set_audit_persist_context(AuditPersistContext(workspace=str(workspace)))
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(cwd=str(workspace), security_engine="ci2lab"),
    )
    records = _read_jsonl(resolve_audit_path_within_workspace(str(workspace)))
    assert any(r["decision"] == "deny" for r in records)


def test_audit_jsonl_experimental_flag(workspace: Path, outside_secret: Path):
    rules = OpenCodePermissionConfig(
        rules={"read": {"*": "allow"}, "external_directory": {"*": "allow"}}
    )
    set_audit_persist_context(
        AuditPersistContext(
            workspace=str(workspace),
            security_engine="opencode_experimental",
        )
    )
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(
            cwd=str(workspace),
            security_engine="opencode_experimental",
            opencode_permissions=rules,
            auto_confirm=True,
        ),
    )
    records = _read_jsonl(resolve_audit_path_within_workspace(str(workspace)))
    assert records
    assert all(r["experimental"] is True for r in records)
    assert all(r["hard_guards_enabled"] is False for r in records)


def test_audit_jsonl_hard_guards_ci2lab(workspace: Path, outside_secret: Path):
    set_audit_persist_context(AuditPersistContext(workspace=str(workspace)))
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(cwd=str(workspace), security_engine="ci2lab"),
    )
    records = _read_jsonl(resolve_audit_path_within_workspace(str(workspace)))
    deny = next(r for r in records if r["decision"] == "deny")
    assert deny["hard_guards_enabled"] is True
    assert deny["experimental"] is False


def test_audit_jsonl_in_run_subdir(workspace: Path, outside_secret: Path):
    set_audit_persist_context(
        AuditPersistContext(
            workspace=str(workspace),
            runs_dir="runs",
            run_id="2026_test_run",
            run_subdir="2026_test_run",
        )
    )
    execute_tool(
        ToolCall("read_file", {"path": str(outside_secret)}, "t1"),
        AgentConfig(cwd=str(workspace), security_engine="ci2lab", runs_dir="runs"),
    )
    path = workspace / "runs" / "2026_test_run" / "security_audit.jsonl"
    assert path.exists()
    records = _read_jsonl(path)
    assert records[0]["run_id"] == "2026_test_run"


def test_comparator_external_path_difference(workspace: Path, outside_secret: Path):
    rows = run_comparison(workspace, outside_path=outside_secret)
    ci2lab = next(
        r
        for r in rows
        if r.case_id == "read_external_allow" and r.engine == "ci2lab"
    )
    opencode = next(
        r
        for r in rows
        if r.case_id == "read_external_allow"
        and r.engine == "opencode_experimental"
        and r.permission_config == "external_allow"
    )
    assert ci2lab.actual_decision == "deny"
    assert opencode.actual_decision == "allow"
    assert ci2lab.passed and opencode.passed


def test_yes_approves_ask_not_deny(workspace: Path):
    rows = run_comparison(workspace)
    yes_ask = next(r for r in rows if r.case_id == "yes_approves_ask" and r.engine == "opencode_experimental")
    yes_deny = next(r for r in rows if r.case_id == "yes_not_deny" and r.engine == "opencode_experimental")
    assert yes_ask.actual_decision == "allow"
    assert yes_deny.actual_decision == "deny"
    assert yes_ask.passed and yes_deny.passed


def test_specific_rule_beats_wildcard():
    rules = OpenCodePermissionConfig(
        rules={"bash": {"*": "allow", "rm *": "deny"}}
    )
    decision = evaluate_opencode_tool(
        "bash",
        {"command": "rm foo"},
        workspace="/tmp/ws",
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "deny"
    assert decision.matched_rule == "bash:rm *"


def test_read_file_alias_uses_read_rules(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"read": {"inside.txt": "deny", "*": "allow"}})
    decision = evaluate_opencode_tool(
        "read_file",
        {"path": "inside.txt"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "deny"
    assert decision.matched_rule == "read:inside.txt"


def test_shell_alias_uses_bash_rules(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"git *": "allow", "*": "ask"}})
    decision = evaluate_opencode_tool(
        "shell",
        {"command": "git status"},
        workspace=str(workspace),
        rules=rules,
        auto_confirm=False,
    )
    assert decision.action.value == "allow"
    assert decision.matched_rule == "bash:git *"


def test_dotenv_matches_opencode_secret_rule(workspace: Path):
    rules = OpenCodePermissionConfig.default_experimental()
    for path in (".env", workspace / ".env", str(workspace / ".env").replace("\\", "/")):
        decision = evaluate_opencode_tool(
            "read_file",
            {"path": path},
            workspace=str(workspace),
            rules=rules,
            auto_confirm=False,
        )
        assert decision.action.value == "deny", f"failed for path={path!r}"
        assert decision.matched_rule is not None
        assert "env" in decision.matched_rule.lower()


@pytest.mark.parametrize(
    ("unix_path", "win_path"),
    [
        ("../outside/secret.txt", "..\\outside\\secret.txt"),
        ("subdir/nested.txt", "subdir\\nested.txt"),
    ],
)
def test_windows_unix_path_matching_same(
    workspace: Path, unix_path: str, win_path: str
):
    rules = OpenCodePermissionConfig(
        rules={
            "read": {"secret.txt": "deny", "*": "allow"},
            "external_directory": {"*": "allow"},
        }
    )
    perm_u, matched_u = _resolve_tool_permission(rules.rules, "read_file", unix_path)
    perm_w, matched_w = _resolve_tool_permission(rules.rules, "read_file", win_path)
    assert perm_u == perm_w
    assert matched_u == matched_w


def test_path_pattern_env_variants():
    rules = {
        "*": "allow",
        ".env": "deny",
        "*.env": "deny",
        ".env.*": "deny",
        "**/.env": "deny",
    }
    for subject in (".env", "foo.env", ".env.local", "config/.env"):
        perm, matched = _match_best_rule(rules, subject, rule_prefix="read:")
        assert perm == "deny", f"{subject} should deny, got {perm} via {matched}"
