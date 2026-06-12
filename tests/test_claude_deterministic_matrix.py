"""Tests P3.0.1 — matriz determinista claude_experimental."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci2lab.security.audit import clear_audit_log
from ci2lab.security.claude_deterministic_matrix import (
    DISPATCH_PASS,
    GATE_PASS,
    SECURITY_FAIL,
    matrix_has_security_fail,
    run_dispatch_matrix,
    run_full_deterministic_matrix,
    run_gate_matrix,
)
from ci2lab.security.claude_live_audit import prepare_audit_workspace
from ci2lab.security.session_permissions import bind_active_session, clear_session_permissions

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_security_state():
    clear_session_permissions()
    bind_active_session(None)
    clear_audit_log()
    yield
    clear_session_permissions()
    bind_active_session(None)
    clear_audit_log()


def test_gate_matrix_all_pass(tmp_path: Path):
    ws = prepare_audit_workspace(tmp_path, repo_root=ROOT)
    results = run_gate_matrix(ws.root, ws.outside_secret)
    assert len(results) == 12
    assert all(r.observed_status == GATE_PASS for r in results), [
        (r.case_id, r.observed_status, r.notes) for r in results if r.observed_status != GATE_PASS
    ]


def test_dispatch_matrix_all_pass(tmp_path: Path):
    ws = prepare_audit_workspace(tmp_path, repo_root=ROOT)
    write_target = ws.root / "tmp_ci2lab_det_test.txt"
    results = run_dispatch_matrix(ws.root, ws.outside_secret, write_target)
    assert len(results) == 12
    assert all(r.observed_status == DISPATCH_PASS for r in results), [
        (r.case_id, r.observed_status, r.notes) for r in results if r.observed_status != DISPATCH_PASS
    ]


def test_full_matrix_no_security_fail(tmp_path: Path):
    gate, dispatch, _ws = run_full_deterministic_matrix(tmp_path, repo_root=ROOT)
    assert not matrix_has_security_fail(gate, dispatch)


def test_external_read_stays_blocked_at_gate(tmp_path: Path):
    ws = prepare_audit_workspace(tmp_path, repo_root=ROOT)
    results = run_gate_matrix(ws.root, ws.outside_secret)
    ext = next(r for r in results if r.case_id == "read_external_blocked")
    assert ext.observed_status == GATE_PASS
    assert ext.matched_rule == "hard:outside_workspace"


def test_yes_does_not_bypass_at_dispatch(tmp_path: Path):
    ws = prepare_audit_workspace(tmp_path, repo_root=ROOT)
    write_target = ws.root / "tmp_ci2lab_det_test.txt"
    results = run_dispatch_matrix(ws.root, ws.outside_secret, write_target)
    case = next(r for r in results if r.case_id == "yes_does_not_bypass_hard_deny")
    assert case.observed_status == DISPATCH_PASS
    assert case.is_error
