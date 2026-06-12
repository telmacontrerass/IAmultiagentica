"""Matriz determinista P3.0.1 — seguridad claude_experimental sin LLM."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.security.audit import (
    AuditPersistContext,
    clear_audit_log,
    set_audit_persist_context,
)
from ci2lab.security.claude_live_audit import (
    EXTERNAL_DECOY,
    SECRET_DECOY,
    detect_leak,
    external_file_exists,
    prepare_audit_workspace,
)
from ci2lab.security.engine import evaluate_tool_gate
from ci2lab.security.opencode_permissions import OpenCodePermissionConfig
from ci2lab.security.opencode_presets import preset_permissions
from ci2lab.security.session_permissions import (
    bind_active_session,
    build_approval_fingerprint,
    clear_session_permissions,
    grant_session_approval,
)

GATE_PASS = "GATE_PASS"
DISPATCH_PASS = "DISPATCH_PASS"
SECURITY_FAIL = "SECURITY_FAIL"
HARNESS_ERROR = "HARNESS_ERROR"

GateDecision = Literal["allow", "ask", "deny"]


@dataclass(frozen=True)
class GateExpectation:
    decision: GateDecision
    matched_rule: str | None = None
    """Regla exacta o prefijo (ej. hard:)."""


@dataclass(frozen=True)
class GateCaseSpec:
    case_id: str
    tool: str
    args: dict[str, Any]
    expectation: GateExpectation
    description: str = ""
    auto_confirm: bool = False
    permissions: OpenCodePermissionConfig | None = None
    session_id: str | None = None
    grant_session_allow: bool = False


@dataclass(frozen=True)
class DispatchCaseSpec:
    case_id: str
    tool: str
    args: dict[str, Any]
    description: str = ""
    auto_confirm: bool = True
    write_tools_enabled: bool = True
    permissions: OpenCodePermissionConfig | None = None
    session_id: str | None = None
    grant_session_allow: bool = False
    expect_blocked: bool = False
    expect_matched_rule: str | None = None
    verify_no_external_file: bool = False
    verify_internal_file: bool = False
    verify_no_decoy_leak: tuple[str, ...] = ()
    verify_no_secret_read: bool = False


@dataclass
class MatrixCaseResult:
    case_id: str
    layer: Literal["gate", "dispatch"]
    observed_status: str
    expected: str
    notes: str = ""
    tool: str = ""
    blocked: bool | None = None
    needs_confirm: bool | None = None
    matched_rule: str | None = None
    tool_outcome: str | None = None
    is_error: bool | None = None
    leaked_decoy: bool = False
    created_external_file: bool = False
    internal_file_ok: bool | None = None
    content_preview: str = ""


def _dev_permissions() -> OpenCodePermissionConfig:
    return OpenCodePermissionConfig(rules=preset_permissions("opencode_dev"))


def _external_allow_permissions() -> OpenCodePermissionConfig:
    return OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "allow"},
        }
    )


def _read_target(ws_root: Path) -> str:
    if (ws_root / "README.md").is_file():
        return "README.md"
    return "pyproject.toml"


def build_gate_cases(ws_root: Path, outside_secret: Path) -> list[GateCaseSpec]:
    read_internal = _read_target(ws_root)
    outside = str(outside_secret)
    return [
        GateCaseSpec(
            case_id="read_internal",
            tool="read_file",
            args={"path": read_internal},
            expectation=GateExpectation(decision="allow"),
            description="lectura interna permitida (opencode_dev)",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="read_external_blocked",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:outside_workspace"
            ),
            description="ruta externa bloqueada por hard guard",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="read_secret_blocked",
            tool="read_file",
            args={"path": ".env.test"},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:secret_file"
            ),
            description="secreto .env.test bloqueado",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="write_internal",
            tool="write_file",
            args={
                "path": "tmp_ci2lab_det_test.txt",
                "content": "hello deterministic",
            },
            expectation=GateExpectation(decision="ask"),
            description="write interno pide confirmación (edit=ask)",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="write_external_blocked",
            tool="write_file",
            args={"path": outside, "content": "owned"},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:outside_workspace"
            ),
            description="write externo bloqueado",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="bash_safe",
            tool="bash",
            args={"command": "git status"},
            expectation=GateExpectation(decision="allow"),
            description="git status permitido por regla git *",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="bash_destructive_blocked",
            tool="bash",
            args={"command": "rm *"},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:bash_blocklist"
            ),
            description="rm * bloqueado por blocklist",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="external_directory_allow_ignored",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:outside_workspace"
            ),
            description="external_directory=allow no relaja workspace",
            permissions=_external_allow_permissions(),
        ),
        GateCaseSpec(
            case_id="yes_does_not_bypass_hard_deny",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:outside_workspace"
            ),
            description="auto_confirm no salta hard deny",
            auto_confirm=True,
            permissions=_external_allow_permissions(),
        ),
        GateCaseSpec(
            case_id="permission_deny_blocks",
            tool="read_file",
            args={"path": read_internal},
            expectation=GateExpectation(decision="deny"),
            description="permission read=deny bloquea archivo interno",
            permissions=OpenCodePermissionConfig(rules={"read": {"*": "deny"}}),
        ),
        GateCaseSpec(
            case_id="permission_allow_after_hard_pass",
            tool="bash",
            args={"command": "git status"},
            expectation=GateExpectation(decision="allow"),
            description="bash git * = allow tras hard pass",
            permissions=OpenCodePermissionConfig(
                rules={"bash": {"*": "deny", "git *": "allow"}}
            ),
        ),
        GateCaseSpec(
            case_id="session_allow_does_not_bypass_hard_deny",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(
                decision="deny", matched_rule="hard:outside_workspace"
            ),
            description="session allow no salta hard deny externo",
            permissions=_external_allow_permissions(),
            session_id="det-sess-hard",
            grant_session_allow=True,
        ),
    ]


def build_dispatch_cases(ws_root: Path, outside_secret: Path) -> list[DispatchCaseSpec]:
    read_internal = _read_target(ws_root)
    outside = str(outside_secret)
    owned_external = str(outside_secret.parent / "owned.txt")
    return [
        DispatchCaseSpec(
            case_id="read_internal",
            tool="read_file",
            args={"path": read_internal},
            description="lectura interna sin fuga",
            verify_no_decoy_leak=(EXTERNAL_DECOY, SECRET_DECOY),
        ),
        DispatchCaseSpec(
            case_id="read_external_blocked",
            tool="read_file",
            args={"path": outside},
            expect_blocked=True,
            expect_matched_rule="hard:outside_workspace",
            verify_no_external_file=True,
            verify_no_decoy_leak=(EXTERNAL_DECOY,),
        ),
        DispatchCaseSpec(
            case_id="read_secret_blocked",
            tool="read_file",
            args={"path": ".env.test"},
            expect_blocked=True,
            expect_matched_rule="hard:secret_file",
            verify_no_secret_read=True,
            verify_no_decoy_leak=(SECRET_DECOY,),
        ),
        DispatchCaseSpec(
            case_id="write_internal",
            tool="write_file",
            args={
                "path": "tmp_ci2lab_det_test.txt",
                "content": "hello deterministic",
            },
            verify_internal_file=True,
            verify_no_decoy_leak=(EXTERNAL_DECOY, SECRET_DECOY),
        ),
        DispatchCaseSpec(
            case_id="write_external_blocked",
            tool="write_file",
            args={"path": owned_external, "content": "owned"},
            expect_blocked=True,
            expect_matched_rule="hard:outside_workspace",
            verify_no_external_file=True,
            verify_no_decoy_leak=(EXTERNAL_DECOY,),
        ),
        DispatchCaseSpec(
            case_id="bash_safe",
            tool="bash",
            args={"command": "python --version"},
            description="comando seguro ejecutado o ask resuelto",
            verify_no_decoy_leak=(EXTERNAL_DECOY, SECRET_DECOY),
        ),
        DispatchCaseSpec(
            case_id="bash_destructive_blocked",
            tool="bash",
            args={"command": "rm *"},
            expect_blocked=True,
            expect_matched_rule="hard:bash_blocklist",
        ),
        DispatchCaseSpec(
            case_id="external_directory_allow_ignored",
            tool="read_file",
            args={"path": outside},
            expect_blocked=True,
            expect_matched_rule="hard:outside_workspace",
            permissions=_external_allow_permissions(),
            verify_no_external_file=True,
            verify_no_decoy_leak=(EXTERNAL_DECOY,),
        ),
        DispatchCaseSpec(
            case_id="yes_does_not_bypass_hard_deny",
            tool="read_file",
            args={"path": outside},
            auto_confirm=True,
            expect_blocked=True,
            expect_matched_rule="hard:outside_workspace",
            permissions=_external_allow_permissions(),
            verify_no_decoy_leak=(EXTERNAL_DECOY, SECRET_DECOY),
        ),
        DispatchCaseSpec(
            case_id="permission_deny_blocks",
            tool="read_file",
            args={"path": read_internal},
            permissions=OpenCodePermissionConfig(rules={"read": {"*": "deny"}}),
            expect_blocked=True,
        ),
        DispatchCaseSpec(
            case_id="permission_allow_after_hard_pass",
            tool="bash",
            args={"command": "git status"},
            permissions=OpenCodePermissionConfig(
                rules={"bash": {"*": "deny", "git *": "allow"}}
            ),
            verify_no_decoy_leak=(EXTERNAL_DECOY, SECRET_DECOY),
        ),
        DispatchCaseSpec(
            case_id="session_allow_does_not_bypass_hard_deny",
            tool="read_file",
            args={"path": outside},
            permissions=_external_allow_permissions(),
            session_id="det-dispatch-sess",
            grant_session_allow=True,
            expect_blocked=True,
            expect_matched_rule="hard:outside_workspace",
            verify_no_decoy_leak=(EXTERNAL_DECOY,),
        ),
    ]


def _gate_decision(gate: Any) -> GateDecision:
    if gate.blocked:
        return "deny"
    if gate.needs_confirm:
        return "ask"
    return "allow"


def _match_rule(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    if expected.endswith(":"):
        return actual.startswith(expected)
    return actual == expected or actual.startswith(expected)


def _agent_config(
    ws_root: Path,
    *,
    permissions: OpenCodePermissionConfig | None = None,
    auto_confirm: bool = False,
    write_tools_enabled: bool = True,
    session_id: str | None = None,
) -> AgentConfig:
    return AgentConfig(
        cwd=str(ws_root),
        security_engine="claude_experimental",
        security_profile="standard",
        opencode_permissions=permissions or _dev_permissions(),
        auto_confirm=auto_confirm,
        require_diff_preview=False,
        write_tools_enabled=write_tools_enabled,
        session_id=session_id,
    )


def _maybe_grant_session(
    spec: GateCaseSpec | DispatchCaseSpec,
    ws_root: Path,
) -> None:
    if not spec.grant_session_allow or not spec.session_id:
        return
    fp = build_approval_fingerprint(
        engine="claude_experimental",
        tool_name=spec.tool,
        args=spec.args,
        matched_rule="hard:outside_workspace",
        external_directory=True,
    )
    grant_session_approval(spec.session_id, fp, "allow_session")


def evaluate_gate_case(
    ws_root: Path,
    spec: GateCaseSpec,
) -> MatrixCaseResult:
    try:
        clear_session_permissions()
        bind_active_session(spec.session_id)
        _maybe_grant_session(spec, ws_root)
        config = _agent_config(
            ws_root,
            permissions=spec.permissions,
            auto_confirm=spec.auto_confirm,
            session_id=spec.session_id,
        )
        gate = evaluate_tool_gate(spec.tool, spec.args, config)
        decision = _gate_decision(gate)
        ok = decision == spec.expectation.decision and _match_rule(
            gate.matched_rule, spec.expectation.matched_rule
        )
        notes = ""
        if not ok:
            notes = (
                f"esperado {spec.expectation.decision}"
                f"{f' rule={spec.expectation.matched_rule!r}' if spec.expectation.matched_rule else ''}; "
                f"observado {decision} rule={gate.matched_rule!r}"
            )
        return MatrixCaseResult(
            case_id=spec.case_id,
            layer="gate",
            observed_status=GATE_PASS if ok else SECURITY_FAIL,
            expected=spec.description or spec.expectation.decision,
            notes=notes,
            tool=spec.tool,
            blocked=gate.blocked,
            needs_confirm=gate.needs_confirm,
            matched_rule=gate.matched_rule,
        )
    except Exception as exc:  # noqa: BLE001
        return MatrixCaseResult(
            case_id=spec.case_id,
            layer="gate",
            observed_status=HARNESS_ERROR,
            expected=spec.description,
            notes=str(exc)[:400],
            tool=spec.tool,
        )
    finally:
        bind_active_session(None)


def evaluate_dispatch_case(
    ws_root: Path,
    spec: DispatchCaseSpec,
    *,
    outside_secret: Path,
    write_target: Path,
) -> MatrixCaseResult:
    try:
        clear_session_permissions()
        clear_audit_log()
        set_audit_persist_context(
            AuditPersistContext(
                workspace=str(ws_root),
                runs_dir="runs",
                run_id=f"det-{spec.case_id}",
                run_subdir=f"det-{spec.case_id}",
                security_engine="claude_experimental",
            )
        )
        bind_active_session(spec.session_id)
        _maybe_grant_session(spec, ws_root)

        if spec.verify_internal_file and write_target.is_file():
            write_target.unlink()

        config = _agent_config(
            ws_root,
            permissions=spec.permissions,
            auto_confirm=spec.auto_confirm,
            write_tools_enabled=spec.write_tools_enabled,
            session_id=spec.session_id,
        )
        gate = evaluate_tool_gate(spec.tool, spec.args, config)
        if spec.expect_blocked and not gate.blocked:
            return MatrixCaseResult(
                case_id=spec.case_id,
                layer="dispatch",
                observed_status=SECURITY_FAIL,
                expected=spec.description or "bloqueado en gate",
                notes=f"gate no bloqueó; rule={gate.matched_rule!r}",
                tool=spec.tool,
                blocked=gate.blocked,
                matched_rule=gate.matched_rule,
            )
        if spec.expect_matched_rule and not _match_rule(
            gate.matched_rule, spec.expect_matched_rule
        ):
            return MatrixCaseResult(
                case_id=spec.case_id,
                layer="dispatch",
                observed_status=SECURITY_FAIL,
                expected=spec.description or spec.expect_matched_rule,
                notes=f"matched_rule={gate.matched_rule!r}",
                tool=spec.tool,
                blocked=gate.blocked,
                matched_rule=gate.matched_rule,
            )

        result = execute_tool(
            ToolCall(spec.tool, spec.args, f"det-{spec.case_id}"),
            config,
        )
        content = result.content or ""
        leaked = detect_leak(content, spec.verify_no_decoy_leak)
        created_external = (
            external_file_exists(outside_secret)
            if spec.verify_no_external_file
            else False
        )
        internal_ok: bool | None = None
        if spec.verify_internal_file:
            internal_ok = write_target.is_file() and "hello" in write_target.read_text(
                encoding="utf-8"
            ).lower()

        failures: list[str] = []
        if spec.expect_blocked:
            if not result.is_error and not gate.blocked:
                failures.append("tool no devolvió error pese a bloqueo esperado")
            if leaked:
                failures.append("fuga de señuelo en salida")
            if created_external:
                failures.append("archivo externo creado")
            if spec.verify_no_secret_read and SECRET_DECOY in content:
                failures.append("contenido secreto leído")
        else:
            if result.is_error and spec.case_id not in {"write_internal"}:
                failures.append(f"error inesperado: {content[:120]}")
            if leaked:
                failures.append("fuga de señuelo")
            if spec.verify_internal_file and internal_ok is False:
                failures.append("archivo interno no creado")
            if created_external:
                failures.append("archivo externo inesperado")

        status = DISPATCH_PASS if not failures else SECURITY_FAIL
        return MatrixCaseResult(
            case_id=spec.case_id,
            layer="dispatch",
            observed_status=status,
            expected=spec.description or "dispatch seguro",
            notes="; ".join(failures),
            tool=spec.tool,
            blocked=gate.blocked,
            matched_rule=gate.matched_rule,
            tool_outcome=result.outcome,
            is_error=result.is_error,
            leaked_decoy=leaked,
            created_external_file=created_external,
            internal_file_ok=internal_ok,
            content_preview=content[:200].replace("\n", " "),
        )
    except Exception as exc:  # noqa: BLE001
        return MatrixCaseResult(
            case_id=spec.case_id,
            layer="dispatch",
            observed_status=HARNESS_ERROR,
            expected=spec.description,
            notes=str(exc)[:400],
            tool=spec.tool,
        )
    finally:
        bind_active_session(None)
        set_audit_persist_context(None)


def run_gate_matrix(
    ws_root: Path,
    outside_secret: Path,
    *,
    cases: list[GateCaseSpec] | None = None,
) -> list[MatrixCaseResult]:
    specs = cases or build_gate_cases(ws_root, outside_secret)
    return [
        evaluate_gate_case(ws_root, spec)
        for spec in specs
    ]


def run_dispatch_matrix(
    ws_root: Path,
    outside_secret: Path,
    write_target: Path,
    *,
    cases: list[DispatchCaseSpec] | None = None,
) -> list[MatrixCaseResult]:
    specs = cases or build_dispatch_cases(ws_root, outside_secret)
    return [
        evaluate_dispatch_case(
            ws_root,
            spec,
            outside_secret=outside_secret,
            write_target=write_target,
        )
        for spec in specs
    ]


def run_full_deterministic_matrix(
    base_dir: Path,
    *,
    repo_root: Path | None = None,
) -> tuple[list[MatrixCaseResult], list[MatrixCaseResult], Any]:
    ws = prepare_audit_workspace(base_dir, repo_root=repo_root)
    gate_results = run_gate_matrix(ws.root, ws.outside_secret)
    dispatch_results = run_dispatch_matrix(
        ws.root,
        ws.outside_secret,
        ws.write_target.parent / "tmp_ci2lab_det_test.txt",
    )
    return gate_results, dispatch_results, ws


def _count_status(results: list[MatrixCaseResult], status: str) -> int:
    return sum(1 for r in results if r.observed_status == status)


def export_deterministic_report(
    gate_results: list[MatrixCaseResult],
    dispatch_results: list[MatrixCaseResult],
    *,
    out_dir: Path,
    workspace_root: Path,
    outside_secret: Path,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results = gate_results + dispatch_results
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "P3.0.1",
        "security_engine": "claude_experimental",
        "workspace": str(workspace_root),
        "outside_secret": str(outside_secret),
        "gate": {
            "total": len(gate_results),
            "gate_pass": _count_status(gate_results, GATE_PASS),
            "security_fail": _count_status(gate_results, SECURITY_FAIL),
            "harness_error": _count_status(gate_results, HARNESS_ERROR),
        },
        "dispatch": {
            "total": len(dispatch_results),
            "dispatch_pass": _count_status(dispatch_results, DISPATCH_PASS),
            "security_fail": _count_status(dispatch_results, SECURITY_FAIL),
            "harness_error": _count_status(dispatch_results, HARNESS_ERROR),
        },
        "overall": {
            "security_engine_deterministic": (
                "PASS"
                if _count_status(gate_results, SECURITY_FAIL) == 0
                and _count_status(gate_results, HARNESS_ERROR) == 0
                else "FAIL"
            ),
            "tool_dispatch_deterministic": (
                "PASS"
                if _count_status(dispatch_results, SECURITY_FAIL) == 0
                and _count_status(dispatch_results, HARNESS_ERROR) == 0
                else "FAIL"
            ),
        },
        "cases": [asdict(r) for r in all_results],
    }

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    fieldnames = [
        "layer",
        "case_id",
        "observed_status",
        "tool",
        "blocked",
        "matched_rule",
        "tool_outcome",
        "is_error",
        "leaked_decoy",
        "created_external_file",
        "internal_file_ok",
        "notes",
        "content_preview",
    ]
    csv_path = out_dir / "results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_results:
            data = asdict(row)
            writer.writerow({k: data.get(k, "") for k in fieldnames})

    md_lines = [
        "# Claude experimental deterministic audit (P3.0.1)",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        f"**Workspace:** `{workspace_root}`",
        "",
        "## Summary",
        "",
        f"- Security engine deterministic (gate): **{summary['overall']['security_engine_deterministic']}**",
        f"- Tool dispatch deterministic: **{summary['overall']['tool_dispatch_deterministic']}**",
        "",
        "### Gate matrix",
        "",
        f"- GATE_PASS: {summary['gate']['gate_pass']}/{summary['gate']['total']}",
        f"- SECURITY_FAIL: {summary['gate']['security_fail']}",
        f"- HARNESS_ERROR: {summary['gate']['harness_error']}",
        "",
        "### Dispatch matrix",
        "",
        f"- DISPATCH_PASS: {summary['dispatch']['dispatch_pass']}/{summary['dispatch']['total']}",
        f"- SECURITY_FAIL: {summary['dispatch']['security_fail']}",
        f"- HARNESS_ERROR: {summary['dispatch']['harness_error']}",
        "",
        "| layer | case_id | status | matched_rule | notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in all_results:
        md_lines.append(
            "| "
            + " | ".join(
                [
                    r.layer,
                    r.case_id,
                    r.observed_status,
                    (r.matched_rule or "")[:36],
                    (r.notes or "")[:50].replace("|", "/"),
                ]
            )
            + " |"
        )
    md_path = out_dir / "report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    audit_copy: Path | None = None
    fallback = workspace_root / ".ci2lab" / "security_audit.jsonl"
    if fallback.is_file():
        audit_copy = out_dir / "security_audit.jsonl"
        audit_copy.write_text(fallback.read_text(encoding="utf-8"), encoding="utf-8")

    paths: dict[str, Path] = {
        "summary": summary_path,
        "csv": csv_path,
        "markdown": md_path,
    }
    if audit_copy:
        paths["security_audit"] = audit_copy
    return paths


def matrix_has_security_fail(
    gate_results: list[MatrixCaseResult],
    dispatch_results: list[MatrixCaseResult],
) -> bool:
    bad = {SECURITY_FAIL, HARNESS_ERROR}
    return any(r.observed_status in bad for r in gate_results + dispatch_results)
