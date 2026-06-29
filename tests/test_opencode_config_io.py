"""Tests P2.6 — import/export/compare configs OpenCode."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import evaluate_tool_gate
from ci2lab.security.gate_check import evaluate_security_gate, load_permission_config
from ci2lab.security.opencode_config_comparison import (
    export_config_comparison_report,
    run_config_comparison,
)
from ci2lab.security.opencode_config_io import (
    bundle_from_preset,
    detect_unsupported_opencode_tools,
    export_ci2lab_format,
    export_opencode_format,
    export_warnings_for_permission,
    extract_opencode_permission,
    load_opencode_config,
    load_opencode_config_bundle,
    normalize_opencode_permission,
    validate_opencode_permission,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "inside.txt").write_text("inside\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    return tmp_path


def test_load_root_level_permission(tmp_path: Path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps(
            {
                "permission": {
                    "edit": "ask",
                    "bash": {"git *": "allow", "rm *": "deny", "*": "ask"},
                    "external_directory": "deny",
                }
            }
        ),
        encoding="utf-8",
    )
    bundle = load_opencode_config_bundle(cfg)
    assert bundle.permission["edit"] == "ask"
    assert bundle.normalized_permission["bash"]["git *"] == "allow"


def test_load_security_permission(tmp_path: Path):
    cfg = tmp_path / "ci2lab.json"
    cfg.write_text(
        json.dumps(
            {
                "security": {
                    "engine": "opencode_experimental",
                    "permission": {"read": "allow", "edit": "deny"},
                }
            }
        ),
        encoding="utf-8",
    )
    perm = extract_opencode_permission(load_opencode_config(cfg))
    assert perm["read"] == "allow"
    assert perm["edit"] == "deny"


def test_invalid_json_fails_clear(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_opencode_config(bad)


def test_invalid_permission_type_fails_clear():
    with pytest.raises(ValueError, match="must be a JSON object"):
        validate_opencode_permission("allow")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid permission action"):
        validate_opencode_permission({"bash": "maybe"})
    with pytest.raises(ValueError, match="value must be a string"):
        validate_opencode_permission({"bash": 123})  # type: ignore[arg-type]


def test_unsupported_tool_warning_not_crash():
    perm = {"read": "allow", "webfetch": "ask", "bash": {"*": "ask"}}
    unsupported = detect_unsupported_opencode_tools(perm)
    assert "webfetch" in unsupported
    warnings = export_warnings_for_permission(perm)
    assert any("webfetch" in w for w in warnings)
    normalized = normalize_opencode_permission(perm)
    assert normalized["bash"]["*"] == "ask"


def test_normalizer_preserves_bash_rules():
    perm = {
        "bash": {
            "git *": "allow",
            "pytest *": "allow",
            "rm *": "deny",
            "*": "ASK",
        }
    }
    out = normalize_opencode_permission(perm)
    assert out["bash"]["git *"] == "allow"
    assert out["bash"]["*"] == "ask"


def test_dry_gate_opencode_config(workspace: Path, tmp_path: Path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps(
            {
                "permission": {
                    "bash": {"git *": "allow", "*": "deny"},
                    "external_directory": "deny",
                }
            }
        ),
        encoding="utf-8",
    )
    bundle = load_opencode_config_bundle(cfg)
    result = evaluate_security_gate(
        engine="opencode_experimental",
        workspace=str(workspace),
        tool="bash",
        target="git status",
        config_bundle=bundle,
    )
    assert result["decision"] == "allow"
    assert result["config_source"] == str(cfg.resolve())
    assert "unsupported_tools" in result
    assert "warnings" in result


def test_show_effective_config(workspace: Path, tmp_path: Path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps({"permission": {"bash": {"git *": "allow", "*": "ask"}}}),
        encoding="utf-8",
    )
    bundle = load_opencode_config_bundle(cfg)
    result = evaluate_security_gate(
        engine="opencode_experimental",
        workspace=str(workspace),
        tool="bash",
        target="git status",
        config_bundle=bundle,
        show_effective_config=True,
    )
    assert "effective_permission" in result
    assert isinstance(result["effective_permission"], dict)


def test_export_opencode_format():
    perm = {"read": "allow", "edit": "ask", "bash": {"*": "ask"}}
    out = export_opencode_format(perm)
    assert "permission" in out
    assert out["permission"]["read"] == "allow"


def test_export_ci2lab_format():
    perm = {"read": "allow", "edit": "ask"}
    out = export_ci2lab_format(perm)
    assert out["security"]["engine"] == "opencode_experimental"
    assert out["security"]["permission"]["read"] == "allow"


def test_export_preset_opencode_dev():
    bundle = bundle_from_preset("opencode_dev")
    out = export_opencode_format(bundle.normalized_permission)
    assert out["permission"]["edit"] == "ask"
    assert out["permission"]["bash"]["git *"] == "allow"


def test_export_warning_external_allow(capsys):
    perm = {"external_directory": "allow", "read": "allow"}
    warnings = export_warnings_for_permission(perm)
    assert any("external_directory=allow" in w for w in warnings)


def test_config_comparator_generates_csv_md(workspace: Path, tmp_path: Path):
    cfg = tmp_path / "opencode_dev.json"
    cfg.write_text(
        json.dumps(
            export_opencode_format(bundle_from_preset("opencode_dev").normalized_permission)
        ),
        encoding="utf-8",
    )
    bundle = load_opencode_config_bundle(cfg)
    rows = run_config_comparison([("opencode_dev.json", bundle)], workspace)
    export = export_config_comparison_report(rows, workspace=workspace)
    assert export.csv_path.is_file()
    assert export.markdown_path.is_file()
    csv_text = export.csv_path.read_text(encoding="utf-8")
    assert "case_id" in csv_text
    assert "read_internal" in csv_text


def test_comparator_risk_note_external_allow(workspace: Path, tmp_path: Path):
    cfg = tmp_path / "risky.json"
    cfg.write_text(
        json.dumps(
            export_opencode_format(
                bundle_from_preset("opencode_external_allowed").normalized_permission
            )
        ),
        encoding="utf-8",
    )
    bundle = load_opencode_config_bundle(cfg)
    rows = run_config_comparison([("risky.json", bundle)], workspace)
    external_rows = [r for r in rows if r.case_id == "read_external"]
    assert external_rows
    assert any(r.risk_note for r in external_rows)


def test_ci2lab_ignores_root_permission(workspace: Path):
    outside = workspace.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    perm_cfg = workspace / "perm.json"
    perm_cfg.write_text(
        json.dumps({"permission": {"read": "allow", "external_directory": "allow"}}),
        encoding="utf-8",
    )
    loaded = load_permission_config(perm_cfg)
    agent = AgentConfig(
        cwd=str(workspace),
        security_engine="ci2lab",
        opencode_permissions=loaded,
    )
    gate = evaluate_tool_gate("read_file", {"path": str(outside)}, agent)
    assert gate.blocked
    assert gate.hard_guards_enabled is True


def test_security_gate_check_script_opencode_config(workspace: Path, tmp_path: Path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(
        json.dumps({"permission": {"bash": {"git *": "allow", "*": "ask"}}}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "security_gate_check.py"),
            "--engine",
            "opencode_experimental",
            "--workspace",
            str(workspace),
            "--opencode-config",
            str(cfg),
            "--tool",
            "bash",
            "--target",
            "git status",
            "--show-effective-config",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["decision"] == "allow"
    assert data.get("config_source")
    assert "effective_permission" in data


def test_security_config_export_script_preset(capsys):
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "security_config_export.py"),
            "--preset",
            "opencode_dev",
            "--format",
            "opencode",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "permission" in data
    assert data["permission"]["bash"]["git *"] == "allow"
