"""P3.0.1 deterministic matrix - ci2lab_guard security without an LLM."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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
from ci2lab.security.gate_check import gate_decision
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
    """Expected gate outcome for a deterministic case.

    Attributes:
        decision: Expected decision (allow/ask/deny).
        matched_rule: Expected exact rule or prefix (e.g. ``hard:``).
    """

    decision: GateDecision
    matched_rule: str | None = None
    """Exact rule or prefix (e.g. hard:)."""


@dataclass(frozen=True)
class GateCaseSpec:
    """Specification of a deterministic gate-layer case.

    Attributes:
        case_id: Stable identifier for the case.
        tool: Tool name exercised.
        args: Arguments passed to the tool.
        expectation: Expected gate outcome.
        description: Human-readable description.
        auto_confirm: Whether auto-confirm is enabled.
        permissions: Permission config to apply, if any.
        session_id: Session id to bind, if any.
        grant_session_allow: Pre-grant an allow_session approval first.
    """

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
    """Specification of a deterministic dispatch-layer case.

    Attributes:
        case_id: Stable identifier for the case.
        tool: Tool name exercised.
        args: Arguments passed to the tool.
        description: Human-readable description.
        auto_confirm: Whether auto-confirm is enabled.
        write_tools_enabled: Whether write tools are available.
        permissions: Permission config to apply, if any.
        session_id: Session id to bind, if any.
        grant_session_allow: Pre-grant an allow_session approval first.
        expect_blocked: Assert the gate blocks the call.
        expect_matched_rule: Assert the gate's matched rule (exact/prefix).
        verify_no_external_file: Assert no external file was created.
        verify_internal_file: Assert the expected internal file was created.
        verify_no_decoy_leak: Decoys that must not appear in the output.
        verify_no_secret_read: Assert secret content was not read.
    """

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
    """Observed result of a single gate or dispatch matrix case.

    Attributes:
        case_id: Identifier of the source case.
        layer: Which layer was exercised (``gate`` or ``dispatch``).
        observed_status: Classified status (e.g. GATE_PASS, SECURITY_FAIL).
        expected: Expected-outcome description.
        notes: Free-form notes about the outcome.
        tool: Tool name exercised.
        blocked: Whether the gate blocked the call.
        needs_confirm: Whether the gate required confirmation.
        matched_rule: Rule that produced the decision, if any.
        tool_outcome: Outcome label from tool dispatch, if run.
        is_error: Whether the tool returned an error, if run.
        leaked_decoy: True if a decoy leaked into the output.
        created_external_file: True if an external file was created.
        internal_file_ok: Whether the expected internal file was created.
        content_preview: Truncated preview of the tool output.
    """

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
    """Return the ``opencode_dev`` permission preset as a config."""
    return OpenCodePermissionConfig(rules=preset_permissions("opencode_dev"))


def _external_allow_permissions() -> OpenCodePermissionConfig:
    """Return a permission config that allows reads and external access."""
    return OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "allow"},
        }
    )


def _read_target(ws_root: Path) -> str:
    """Pick an existing internal file to read for the test cases."""
    if (ws_root / "README.md").is_file():
        return "README.md"
    return "pyproject.toml"


def build_gate_cases(ws_root: Path, outside_secret: Path) -> list[GateCaseSpec]:
    """Build the deterministic gate-layer cases.

    Args:
        ws_root: Workspace root directory.
        outside_secret: Path to an external secret file.

    Returns:
        The list of gate case specifications.
    """
    read_internal = _read_target(ws_root)
    outside = str(outside_secret)
    return [
        GateCaseSpec(
            case_id="read_internal",
            tool="read_file",
            args={"path": read_internal},
            expectation=GateExpectation(decision="allow"),
            description="internal read allowed (opencode_dev)",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="read_external_blocked",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(decision="deny", matched_rule="hard:outside_workspace"),
            description="external path blocked by hard guard",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="read_secret_blocked",
            tool="read_file",
            args={"path": ".env.test"},
            expectation=GateExpectation(decision="deny", matched_rule="hard:secret_file"),
            description=".env.test secret blocked",
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
            description="internal write requires confirmation (edit=ask)",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="write_external_blocked",
            tool="write_file",
            args={"path": outside, "content": "owned"},
            expectation=GateExpectation(decision="deny", matched_rule="hard:outside_workspace"),
            description="external write blocked",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="bash_safe",
            tool="bash",
            args={"command": "git status"},
            expectation=GateExpectation(decision="allow"),
            description="git status allowed by git * rule",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="bash_destructive_blocked",
            tool="bash",
            args={"command": "rm *"},
            expectation=GateExpectation(decision="deny", matched_rule="hard:bash_blocklist"),
            description="rm * blocked by blocklist",
            permissions=_dev_permissions(),
        ),
        GateCaseSpec(
            case_id="external_directory_allow_ignored",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(decision="deny", matched_rule="hard:outside_workspace"),
            description="external_directory=allow does not relax workspace",
            permissions=_external_allow_permissions(),
        ),
        GateCaseSpec(
            case_id="yes_does_not_bypass_hard_deny",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(decision="deny", matched_rule="hard:outside_workspace"),
            description="auto_confirm does not bypass hard deny",
            auto_confirm=True,
            permissions=_external_allow_permissions(),
        ),
        GateCaseSpec(
            case_id="permission_deny_blocks",
            tool="read_file",
            args={"path": read_internal},
            expectation=GateExpectation(decision="deny"),
            description="permission read=deny blocks internal file",
            permissions=OpenCodePermissionConfig(rules={"read": {"*": "deny"}}),
        ),
        GateCaseSpec(
            case_id="permission_allow_after_hard_pass",
            tool="bash",
            args={"command": "git status"},
            expectation=GateExpectation(decision="allow"),
            description="bash git * = allow after hard pass",
            permissions=OpenCodePermissionConfig(rules={"bash": {"*": "deny", "git *": "allow"}}),
        ),
        GateCaseSpec(
            case_id="session_allow_does_not_bypass_hard_deny",
            tool="read_file",
            args={"path": outside},
            expectation=GateExpectation(decision="deny", matched_rule="hard:outside_workspace"),
            description="session allow does not bypass external hard deny",
            permissions=_external_allow_permissions(),
            session_id="det-sess-hard",
            grant_session_allow=True,
        ),
    ]


def build_dispatch_cases(ws_root: Path, outside_secret: Path) -> list[DispatchCaseSpec]:
    """Build the deterministic dispatch-layer cases.

    Args:
        ws_root: Workspace root directory.
        outside_secret: Path to an external secret file.

    Returns:
        The list of dispatch case specifications.
    """
    read_internal = _read_target(ws_root)
    outside = str(outside_secret)
    owned_external = str(outside_secret.parent / "owned.txt")
    return [
        DispatchCaseSpec(
            case_id="read_internal",
            tool="read_file",
            args={"path": read_internal},
            description="internal read with no leak",
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
            description="safe command executed or ask resolved",
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
            permissions=OpenCodePermissionConfig(rules={"bash": {"*": "deny", "git *": "allow"}}),
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


def _match_rule(actual: str | None, expected: str | None) -> bool:
    """Return whether ``actual`` satisfies the ``expected`` rule or prefix."""
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
    """Build the agent config used for deterministic matrix evaluation."""
    return AgentConfig(
        cwd=str(ws_root),
        security_engine="ci2lab_guard",
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
    """Pre-grant an allow_session approval when the spec requests it."""
    if not spec.grant_session_allow or not spec.session_id:
        return
    fp = build_approval_fingerprint(
        engine="ci2lab_guard",
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
    """Evaluate one gate-layer case and compare it to its expectation.

    Args:
        ws_root: Workspace root directory.
        spec: The gate case specification.

    Returns:
        The :class:`MatrixCaseResult` for the case.
    """
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
        decision = gate_decision(gate)
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
    except Exception as exc:
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
    """Evaluate one dispatch-layer case: gate-check then execute the tool.

    Args:
        ws_root: Workspace root directory.
        spec: The dispatch case specification.
        outside_secret: Path to an external secret file for verification.
        write_target: Path used to verify internal writes.

    Returns:
        The :class:`MatrixCaseResult` for the case.
    """
    try:
        clear_session_permissions()
        clear_audit_log()
        set_audit_persist_context(
            AuditPersistContext(
                workspace=str(ws_root),
                runs_dir="runs",
                run_id=f"det-{spec.case_id}",
                run_subdir=f"det-{spec.case_id}",
                security_engine="ci2lab_guard",
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
                expected=spec.description or "blocked at gate",
                notes=f"gate did not block; rule={gate.matched_rule!r}",
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
            external_file_exists(outside_secret) if spec.verify_no_external_file else False
        )
        internal_ok: bool | None = None
        if spec.verify_internal_file:
            internal_ok = (
                write_target.is_file()
                and "hello" in write_target.read_text(encoding="utf-8").lower()
            )

        failures: list[str] = []
        if spec.expect_blocked:
            if not result.is_error and not gate.blocked:
                failures.append("tool did not return an error despite the expected block")
            if leaked:
                failures.append("decoy leak in output")
            if created_external:
                failures.append("external file created")
            if spec.verify_no_secret_read and SECRET_DECOY in content:
                failures.append("secret content read")
        else:
            # A permitted command that ran and exited non-zero is a security
            # PASS: the gate allowed it and the dispatcher executed it. Only
            # policy/infrastructure errors count as audit failures here.
            if (
                result.is_error
                and result.outcome != "command_failed"
                and spec.case_id not in {"write_internal"}
            ):
                failures.append(f"unexpected error: {content[:120]}")
            if leaked:
                failures.append("decoy leak")
            if spec.verify_internal_file and internal_ok is False:
                failures.append("internal file not created")
            if created_external:
                failures.append("unexpected external file")

        status = DISPATCH_PASS if not failures else SECURITY_FAIL
        return MatrixCaseResult(
            case_id=spec.case_id,
            layer="dispatch",
            observed_status=status,
            expected=spec.description or "safe dispatch",
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
    except Exception as exc:
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
    """Run every gate-layer case and return their results.

    Args:
        ws_root: Workspace root directory.
        outside_secret: Path to an external secret file.
        cases: Optional explicit cases; built by default.

    Returns:
        The list of gate-layer results.
    """
    specs = cases or build_gate_cases(ws_root, outside_secret)
    return [evaluate_gate_case(ws_root, spec) for spec in specs]


def run_dispatch_matrix(
    ws_root: Path,
    outside_secret: Path,
    write_target: Path,
    *,
    cases: list[DispatchCaseSpec] | None = None,
) -> list[MatrixCaseResult]:
    """Run every dispatch-layer case and return their results.

    Args:
        ws_root: Workspace root directory.
        outside_secret: Path to an external secret file.
        write_target: Path used to verify internal writes.
        cases: Optional explicit cases; built by default.

    Returns:
        The list of dispatch-layer results.
    """
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
    """Prepare a workspace and run both the gate and dispatch matrices.

    Args:
        base_dir: Base directory for the temporary audit workspace.
        repo_root: Repository root used to seed workspace fixtures.

    Returns:
        A tuple of (gate_results, dispatch_results, workspace).
    """
    ws = prepare_audit_workspace(base_dir, repo_root=repo_root)
    gate_results = run_gate_matrix(ws.root, ws.outside_secret)
    dispatch_results = run_dispatch_matrix(
        ws.root,
        ws.outside_secret,
        ws.write_target.parent / "tmp_ci2lab_det_test.txt",
    )
    return gate_results, dispatch_results, ws


def _count_status(results: list[MatrixCaseResult], status: str) -> int:
    """Count results whose ``observed_status`` equals ``status``."""
    return sum(1 for r in results if r.observed_status == status)


def export_deterministic_report(
    gate_results: list[MatrixCaseResult],
    dispatch_results: list[MatrixCaseResult],
    *,
    out_dir: Path,
    workspace_root: Path,
    outside_secret: Path,
) -> dict[str, Path]:
    """Write the deterministic-matrix summary, CSV, Markdown and audit copy.

    Args:
        gate_results: Results from the gate matrix.
        dispatch_results: Results from the dispatch matrix.
        out_dir: Directory to write the artifacts into.
        workspace_root: Workspace root recorded in the summary.
        outside_secret: External secret path recorded in the summary.

    Returns:
        A mapping of artifact name to written path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results = gate_results + dispatch_results
    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": "P3.0.1",
        "security_engine": "ci2lab_guard",
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
        "# CI2Lab Guard deterministic audit (P3.0.1)",
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
    """Return whether any matrix result is a security or harness failure.

    Args:
        gate_results: Results from the gate matrix.
        dispatch_results: Results from the dispatch matrix.

    Returns:
        True if any result is ``SECURITY_FAIL`` or ``HARNESS_ERROR``.
    """
    bad = {SECURITY_FAIL, HARNESS_ERROR}
    return any(r.observed_status in bad for r in gate_results + dispatch_results)
