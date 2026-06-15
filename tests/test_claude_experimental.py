"""Tests P2.8 — motor claude_experimental (hard guards + permission UX)."""

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from ci2lab.config import Ci2LabConfig, _apply_mapping
from ci2lab.harness.security_profiles import SecurityConfig, resolved_opencode_permissions
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.approval_prompt import (
    confirm_opencode_ask,
    prompt_opencode_approval,
    uses_modern_permission_prompt,
)
from ci2lab.security.audit import clear_audit_log, get_audit_log
from ci2lab.security.comparison import run_comparison
from ci2lab.security.engine import (
    CLAUDE_EXTERNAL_ALLOW_IGNORED,
    SecurityEngineName,
    enforce_ci2lab_hard_policy,
    evaluate_tool_gate,
    normalize_security_engine,
)
from ci2lab.security.gate_check import evaluate_security_gate
from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
from ci2lab.security.permissions_dashboard import build_retry_plan, load_audit_events
from ci2lab.security.session_permissions import (
    bind_active_session,
    build_approval_fingerprint,
    clear_session_permissions,
    grant_session_approval,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside\n", encoding="utf-8")
    (ws / ".env").write_text("SECRET=1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside\n", encoding="utf-8")
    return ws


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    return (tmp_path / "outside" / "secret.txt").resolve()


@pytest.fixture(autouse=True)
def _reset_state():
    clear_session_permissions()
    bind_active_session(None)
    clear_audit_log()
    yield
    clear_session_permissions()
    bind_active_session(None)
    clear_audit_log()


def _external_allow_rules() -> OpenCodePermissionConfig:
    return OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "allow"},
        }
    )


def _dev_rules() -> OpenCodePermissionConfig:
    from ci2lab.security.opencode_presets import preset_permissions

    return OpenCodePermissionConfig(rules=preset_permissions("opencode_dev"))


def test_claude_engine_in_config():
    cfg = _apply_mapping(
        Ci2LabConfig(),
        {"security": {"engine": "claude_experimental", "permission_preset": "opencode_dev"}},
    )
    assert cfg.security.engine == "claude_experimental"


def test_claude_engine_cli_flag():
    proc = subprocess.run(
        [sys.executable, "-m", "ci2lab", "doctor"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0


def test_default_engine_claude_experimental():
    assert normalize_security_engine(None) == SecurityEngineName.CLAUDE_EXPERIMENTAL.value


def test_unknown_engine_fails():
    with pytest.raises(Exception, match="desconocido"):
        normalize_security_engine("not_a_real_engine")


def test_claude_blocks_external_despite_external_allow(
    workspace: Path, outside_secret: Path
):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=_external_allow_rules(),
    )
    gate = evaluate_tool_gate("read_file", {"path": str(outside_secret)}, config)
    assert gate.blocked
    assert gate.matched_rule == "hard:outside_workspace"
    assert gate.external_directory is True
    assert gate.hard_guards_enabled is True
    assert gate.risk_note == CLAUDE_EXTERNAL_ALLOW_IGNORED


def test_claude_blocks_dotenv_despite_read_allow(workspace: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=OpenCodePermissionConfig(rules={"read": {"*": "allow"}}),
    )
    gate = evaluate_tool_gate("read_file", {"path": ".env"}, config)
    assert gate.blocked
    assert gate.matched_rule == "hard:secret_file"


def test_claude_blocks_rm_despite_bash_allow_rule(workspace: Path):
    rules = OpenCodePermissionConfig(
        rules={"bash": {"*": "allow", "rm *": "allow"}},
    )
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=rules,
    )
    gate = evaluate_tool_gate("bash", {"command": "rm *"}, config)
    assert gate.blocked
    assert gate.matched_rule == "hard:bash_blocklist"


def test_yes_does_not_skip_hard_deny(workspace: Path, outside_secret: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=_external_allow_rules(),
        auto_confirm=True,
    )
    gate = evaluate_tool_gate("read_file", {"path": str(outside_secret)}, config)
    assert gate.blocked


def test_claude_allows_git_status(workspace: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=_dev_rules(),
    )
    gate = evaluate_tool_gate("bash", {"command": "git status"}, config)
    assert not gate.blocked
    assert not gate.needs_confirm
    assert gate.permission_layer_enabled is True


def test_claude_asks_unknown_bash(workspace: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=_dev_rules(),
        auto_confirm=False,
    )
    gate = evaluate_tool_gate("bash", {"command": "echo safe"}, config)
    assert gate.needs_confirm
    assert gate.permission_layer_enabled is True


def test_claude_permission_deny(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "deny"}})
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=rules,
    )
    gate = evaluate_tool_gate("bash", {"command": "git status"}, config)
    assert gate.blocked
    assert gate.matched_rule is not None
    assert not str(gate.matched_rule or "").startswith("hard:")


@pytest.mark.parametrize(
    ("command", "expected_rule_prefix"),
    [
        ("rm archivo.txt", "bash:rm *"),
        ("rm otra_cosa.txt", "bash:rm *"),
        ("rm carpeta", "bash:rm *"),
        ("del archivo.txt", "bash:del *"),
        ("rmdir carpeta", "bash:rmdir *"),
        ("rd carpeta", "bash:rd *"),
        ("erase archivo.txt", "bash:erase *"),
        ("Remove-Item archivo.txt", "bash:Remove-Item *"),
        ("Remove-Item -Recurse carpeta", "bash:Remove-Item *"),
        ("Remove-Item -Force archivo.txt", "bash:Remove-Item *"),
        ("Remove-Item -Recurse -Force carpeta", "bash:Remove-Item *"),
    ],
)
def test_claude_default_deny_patterns_generalized(
    workspace: Path, command: str, expected_rule_prefix: str
):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
    )
    gate = evaluate_tool_gate("bash", {"command": command}, config)
    assert gate.blocked
    assert (gate.matched_rule or "").startswith(expected_rule_prefix)
    assert not str(gate.matched_rule or "").startswith("hard:")


@pytest.mark.parametrize(
    "command",
    [
        "rmdir /s carpeta",
        "rd /s carpeta",
    ],
)
def test_claude_recursive_cmd_variants_blocked(workspace: Path, command: str):
    """rmdir /s y rd /s deben bloquearse (hard guard o permission deny)."""
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
    )
    gate = evaluate_tool_gate("bash", {"command": command}, config)
    assert gate.blocked


def test_claude_safe_commands_not_denied(workspace: Path):
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
    )
    git = evaluate_tool_gate("bash", {"command": "git status"}, config)
    assert not git.blocked
    assert git.matched_rule == "bash:git *"

    echo = evaluate_tool_gate("bash", {"command": "echo safe"}, config)
    assert not echo.blocked
    assert echo.matched_rule == "bash:*"


def test_security_permission_over_root():
    sec = SecurityConfig(
        engine="claude_experimental",
        permission={"bash": {"*": "deny"}},
    )
    perms = resolved_opencode_permissions(
        sec,
        root_permission={"bash": {"*": "allow"}},
    )
    assert perms.rules["bash"]["*"] == "deny"


def test_preset_opencode_dev_claude(workspace: Path):
    sec = SecurityConfig(
        engine="claude_experimental",
        permission_preset="opencode_dev",
    )
    perms = resolved_opencode_permissions(sec)
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=perms,
    )
    gate = evaluate_tool_gate("bash", {"command": "pytest -q"}, config)
    assert not gate.blocked


def test_modern_prompt_used_for_claude():
    assert uses_modern_permission_prompt("claude_experimental")


def test_claude_prompt_menu():
    out = StringIO()
    choice = prompt_opencode_approval(
        __import__(
            "ci2lab.security.approval_prompt",
            fromlist=["OpenCodeApprovalDecision"],
        ).OpenCodeApprovalDecision(
            tool_name="bash",
            target_summary="echo x",
            matched_rule="bash:*",
        ),
        security_engine="claude_experimental",
        input_func=lambda _: "a",
        output_func=out.write,
    )
    assert "claude_experimental" in out.getvalue()
    assert choice.value == "allow_once"


def test_allow_session_second_call(workspace: Path):
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})
    args = {"command": "echo safe"}
    fp = build_approval_fingerprint(
        engine="claude_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    bind_active_session("sess-c")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=rules,
        session_id="sess-c",
    )
    gate1 = evaluate_tool_gate("bash", args, config)
    assert gate1.needs_confirm
    grant_session_approval("sess-c", fp, "allow_session")
    gate2 = evaluate_tool_gate("bash", args, config)
    assert gate2.session_approval_used
    assert not gate2.needs_confirm


def test_allow_session_no_skip_hard(workspace: Path, outside_secret: Path):
    fp = build_approval_fingerprint(
        engine="claude_experimental",
        tool_name="read_file",
        args={"path": str(outside_secret)},
        matched_rule="hard:outside_workspace",
        external_directory=True,
    )
    grant_session_approval("sess-x", fp, "allow_session")
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=_external_allow_rules(),
        session_id="sess-x",
    )
    gate = evaluate_tool_gate(
        "read_file", {"path": str(outside_secret)}, config
    )
    assert gate.blocked


def test_opencode_session_does_not_affect_claude(workspace: Path):
    args = {"command": "echo safe"}
    fp_opencode = build_approval_fingerprint(
        engine="opencode_experimental",
        tool_name="bash",
        args=args,
        matched_rule="bash:*",
        external_directory=False,
    )
    grant_session_approval("sess-m", fp_opencode, "allow_session")
    rules = OpenCodePermissionConfig(rules={"bash": {"*": "ask"}})
    config = AgentConfig(
        cwd=str(workspace),
        security_engine="claude_experimental",
        opencode_permissions=rules,
        session_id="sess-m",
        auto_confirm=False,
    )
    gate = evaluate_tool_gate("bash", args, config)
    assert gate.needs_confirm
    assert not gate.session_approval_used


def test_audit_marks_claude_engine(workspace: Path):
    execute_tool(
        ToolCall("read_file", {"path": "inside.txt"}, "t1"),
        AgentConfig(
            cwd=str(workspace),
            security_engine="claude_experimental",
            opencode_permissions=_dev_rules(),
            auto_confirm=True,
        ),
    )
    entries = get_audit_log()
    assert any(
        e.extra.get("security_engine") == "claude_experimental" for e in entries
    )
    assert any(e.extra.get("hard_guards_enabled") for e in entries)


def test_retry_plan_hard_deny_claude(workspace: Path, outside_secret: Path):
    event = {
        "event_id": "abc",
        "security_engine": "claude_experimental",
        "tool": "read_file",
        "target": str(outside_secret),
        "decision": "deny",
        "reason": "outside_workspace",
        "matched_rule": "hard:outside_workspace",
        "external_directory": True,
        "hard_guards_enabled": True,
        "outcome": "blocked_by_workspace",
    }
    plan = build_retry_plan(event, workspace=str(workspace))
    text = " ".join(plan["recommendations"]).lower()
    assert "hard" in text or "workspace" in text
    assert "if_retried_claude_experimental" in plan


def test_comparator_includes_claude(workspace: Path, outside_secret: Path):
    rows = run_comparison(workspace, outside_path=outside_secret)
    assert any(r.engine == "claude_experimental" for r in rows)
    claude_ext = next(
        r
        for r in rows
        if r.case_id == "read_external_allow"
        and r.engine == "claude_experimental"
        and r.permission_config == "external_allow"
    )
    assert claude_ext.actual_decision == "deny"
    assert claude_ext.passed


def test_comparator_three_engines_external(workspace: Path, outside_secret: Path):
    rows = run_comparison(workspace, outside_path=outside_secret)
    ci2 = next(
        r
        for r in rows
        if r.case_id == "read_external_allow" and r.engine == "ci2lab"
    )
    opn = next(
        r
        for r in rows
        if r.case_id == "read_external_allow"
        and r.engine == "opencode_experimental"
        and r.permission_config == "external_allow"
    )
    cla = next(
        r
        for r in rows
        if r.case_id == "read_external_allow"
        and r.engine == "claude_experimental"
        and r.permission_config == "external_allow"
    )
    assert ci2.actual_decision == "deny"
    assert opn.actual_decision == "allow"
    assert cla.actual_decision == "deny"


def test_dry_gate_claude_git(workspace: Path):
    result = evaluate_security_gate(
        engine="claude_experimental",
        workspace=str(workspace),
        tool="bash",
        target="git status",
    )
    assert result["engine"] == "claude_experimental"
    assert result["experimental"] is True


def test_enforce_hard_policy_includes_claude():
    assert enforce_ci2lab_hard_policy("claude_experimental")
    assert not enforce_ci2lab_hard_policy("opencode_experimental")


def test_build_agent_config_uses_runtime_security():
    from ci2lab.harness import default_selection
    from ci2lab.pipeline import build_agent_config

    runtime = Ci2LabConfig(
        security=SecurityConfig(engine="claude_experimental", profile="standard"),
    )
    selection = default_selection("test:1b")
    agent = build_agent_config(runtime, selection, cwd=str(Path.cwd()))
    assert agent.security_engine == "claude_experimental"
    assert agent.opencode_permissions is not None


def test_security_gate_check_default_engine(workspace: Path):
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "security_gate_check.py"),
            "--workspace",
            str(workspace),
            "--tool",
            "bash",
            "--target",
            "rm archivo.txt",
        ],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["engine"] == "claude_experimental"
    assert data["decision"] == "deny"
    assert data["blocked"] is True
