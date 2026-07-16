"""Automatic comparator between the ci2lab and opencode_experimental security engines."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import evaluate_tool_gate
from ci2lab.security.gate_check import target_label
from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    evaluate_opencode_tool,
)
from ci2lab.security.opencode_presets import PRESET_NAMES, preset_permissions

_CSV_COLUMNS = [
    "case_id",
    "description",
    "engine",
    "permission_config_name",
    "tool",
    "target_or_command",
    "expected_decision",
    "actual_decision",
    "matched_rule",
    "external_directory",
    "hard_guards_enabled",
    "experimental",
    "passed",
    "risk_note",
]


@dataclass(frozen=True)
class ComparisonCase:
    """A single cross-engine comparison case and its expected decisions.

    Attributes:
        case_id: Stable identifier for the case.
        description: Human-readable description.
        tool: Tool name exercised by the case.
        args: Arguments passed to the tool.
        expected_ci2lab: Expected decision for the ci2lab engine.
        expected_opencode: Map of permission-config key to expected decision.
        expected_claude: Same as above for the ci2lab_guard engine.
        notes: Free-form notes.
        risk_note: Advisory risk note for the case.
    """

    case_id: str
    description: str
    tool: str
    args: dict[str, Any]
    expected_ci2lab: str
    expected_opencode: dict[str, str]
    """permission_config_key -> expected decision (allow|ask|deny)."""
    expected_claude: dict[str, str] = field(default_factory=dict)
    """permission_config_key -> expected decision for ci2lab_guard."""
    notes: str = ""
    risk_note: str = ""


@dataclass
class ComparisonRow:
    """One evaluated row: a case run against a specific engine and config.

    Attributes:
        case_id: Identifier of the source case.
        description: Human-readable description.
        engine: Engine the case was evaluated against.
        permission_config: Name of the permission config used.
        tool: Tool name exercised.
        target_or_command: Target path or command label.
        expected_decision: Decision the case expected.
        actual_decision: Decision actually produced.
        matched_rule: Rule that produced the decision, if any.
        passed: True when expected and actual decisions match.
        notes: Free-form notes.
        external_directory: True if the target was outside the workspace.
        hard_guards_enabled: True if hard guards applied.
        experimental: True if produced by an experimental engine.
        risk_note: Advisory risk note for the row.
        permission_layer_enabled: True if the permission layer applied.
    """

    case_id: str
    description: str
    engine: str
    permission_config: str
    tool: str
    target_or_command: str
    expected_decision: str
    actual_decision: str
    matched_rule: str | None
    passed: bool
    notes: str = ""
    external_directory: bool = False
    hard_guards_enabled: bool = True
    experimental: bool = False
    risk_note: str = ""
    permission_layer_enabled: bool = False


def _gate_decision(
    tool: str,
    args: dict[str, Any],
    config: AgentConfig,
) -> tuple[str, str | None, bool, bool, bool, bool, str | None]:
    """Evaluate the gate and flatten its result into a comparison tuple.

    Returns:
        A tuple of (decision, matched_rule, external_directory,
        hard_guards_enabled, experimental, permission_layer_enabled,
        risk_note).
    """
    gate = evaluate_tool_gate(tool, args, config)
    if gate.blocked:
        decision = "deny"
    elif gate.needs_confirm:
        decision = "ask"
    else:
        decision = "allow"
    return (
        decision,
        gate.matched_rule,
        gate.external_directory,
        gate.hard_guards_enabled,
        gate.experimental,
        gate.permission_layer_enabled,
        gate.risk_note,
    )


def _opencode_decision(
    tool: str,
    args: dict[str, Any],
    *,
    workspace: str,
    rules: OpenCodePermissionConfig,
    auto_confirm: bool,
) -> tuple[str, str | None, bool]:
    """Evaluate the OpenCode permission layer and flatten the decision.

    Returns:
        A tuple of (decision, matched_rule, external_directory).
    """
    decision = evaluate_opencode_tool(
        tool,
        args,
        workspace=workspace,
        rules=rules,
        auto_confirm=auto_confirm,
    )
    action = decision.action.value
    if action == "confirm":
        return "ask", decision.matched_rule, decision.external_directory
    return action, decision.matched_rule, decision.external_directory


def _risk_note_for_row(
    *,
    engine: str,
    case: ComparisonCase,
    external_directory: bool,
) -> str:
    """Derive an advisory risk note for a comparison row."""
    if case.risk_note:
        return case.risk_note
    if case.notes:
        return case.notes
    if engine == "opencode_experimental" and external_directory:
        return "opencode may allow external paths depending on external_directory"
    if engine == "ci2lab_guard" and external_directory:
        return "ci2lab_guard ignores external_directory=allow; hard workspace blocks"
    if engine == "ci2lab" and external_directory:
        return "ci2lab always blocks paths outside the workspace"
    return ""


PERMISSION_PRESETS: dict[str, OpenCodePermissionConfig] = {
    "default_experimental": OpenCodePermissionConfig.default_experimental(),
    "external_deny": OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "deny"},
        }
    ),
    "external_ask": OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "ask"},
        }
    ),
    "external_allow": OpenCodePermissionConfig(
        rules={
            "read": {"*": "allow"},
            "external_directory": {"*": "allow"},
        }
    ),
    "bash_rm_deny": OpenCodePermissionConfig(
        rules={
            "bash": {"*": "allow", "rm *": "deny"},
        }
    ),
    "bash_ask_default": OpenCodePermissionConfig.default_experimental(),
    "yes_ask_bash": OpenCodePermissionConfig(
        rules={"bash": {"*": "ask", "rm *": "deny"}},
    ),
}
for _preset_name in PRESET_NAMES:
    PERMISSION_PRESETS[_preset_name] = OpenCodePermissionConfig(
        rules=preset_permissions(_preset_name)
    )


def build_comparison_cases(
    workspace: Path,
    outside_path: Path,
    env_path: Path,
) -> list[ComparisonCase]:
    """Build the standard matrix of cross-engine comparison cases.

    Args:
        workspace: Path to the workspace root.
        outside_path: Path of an external file used by external-access cases.
        env_path: Path of a ``.env`` file used by secret-policy cases.

    Returns:
        The list of comparison cases.
    """
    inside = workspace / "inside.txt"
    return [
        ComparisonCase(
            case_id="read_inside",
            description="Read a file inside the workspace",
            tool="read_file",
            args={"path": str(inside)},
            expected_ci2lab="allow",
            expected_opencode={"default_experimental": "allow"},
            expected_claude={"default_experimental": "allow", "opencode_dev": "allow"},
        ),
        ComparisonCase(
            case_id="read_external_deny",
            description="Read outside the workspace with external_directory=deny",
            tool="read_file",
            args={"path": str(outside_path)},
            expected_ci2lab="deny",
            expected_opencode={
                "default_experimental": "deny",
                "external_deny": "deny",
            },
            notes="ci2lab always blocks external paths",
            risk_note="sandbox-first: ci2lab ignores external_directory allow",
        ),
        ComparisonCase(
            case_id="read_external_ask",
            description="Read outside the workspace with external_directory=ask",
            tool="read_file",
            args={"path": str(outside_path)},
            expected_ci2lab="deny",
            expected_opencode={"external_ask": "ask"},
        ),
        ComparisonCase(
            case_id="read_external_allow",
            description="Read outside the workspace with external_directory=allow",
            tool="read_file",
            args={"path": str(outside_path)},
            expected_ci2lab="deny",
            expected_opencode={
                "external_allow": "allow",
                "opencode_external_allowed": "allow",
            },
            notes="sandbox-first vs permission-first",
            risk_note="UNSAFE: opencode can read outside the workspace",
            expected_claude={
                "external_allow": "deny",
                "opencode_external_allowed": "deny",
                "default_experimental": "deny",
            },
        ),
        ComparisonCase(
            case_id="preset_external_paranoid",
            description="Preset opencode_paranoid blocks external path",
            tool="read_file",
            args={"path": str(outside_path)},
            expected_ci2lab="deny",
            expected_opencode={"opencode_paranoid": "deny", "opencode_dev": "deny"},
            risk_note="paranoid/dev presets: external_directory deny",
        ),
        ComparisonCase(
            case_id="preset_write_paranoid",
            description="Preset opencode_paranoid blocks write_file",
            tool="write_file",
            args={"path": "new.txt", "content": "x"},
            expected_ci2lab="ask",
            expected_opencode={"opencode_paranoid": "deny", "opencode_dev": "ask"},
            risk_note="paranoid preset: edit deny",
        ),
        ComparisonCase(
            case_id="read_dotenv",
            description="Read .env inside the workspace",
            tool="read_file",
            args={"path": str(env_path)},
            expected_ci2lab="deny",
            expected_opencode={"default_experimental": "deny"},
            expected_claude={"default_experimental": "deny", "opencode_dev": "deny"},
        ),
        ComparisonCase(
            case_id="bash_git_status",
            description="git status",
            tool="bash",
            args={"command": "git status"},
            expected_ci2lab="ask",
            expected_opencode={"default_experimental": "allow"},
            expected_claude={"default_experimental": "allow", "opencode_dev": "allow"},
        ),
        ComparisonCase(
            case_id="bash_pytest_version",
            description="pytest --version",
            tool="bash",
            args={"command": "pytest --version"},
            expected_ci2lab="ask",
            expected_opencode={"default_experimental": "allow"},
        ),
        ComparisonCase(
            case_id="bash_rm_wildcard",
            description="rm * / del * / Remove-Item *",
            tool="bash",
            args={"command": "rm *"},
            expected_ci2lab="deny",
            expected_opencode={"default_experimental": "deny"},
            expected_claude={
                "default_experimental": "deny",
                "bash_rm_deny": "deny",
                "opencode_dev": "deny",
            },
        ),
        ComparisonCase(
            case_id="bash_unmatched",
            description="bash command with no specific rule",
            tool="bash",
            args={"command": "echo safe"},
            expected_ci2lab="ask",
            expected_opencode={"default_experimental": "ask"},
            expected_claude={"default_experimental": "ask", "opencode_dev": "ask"},
        ),
        ComparisonCase(
            case_id="yes_approves_ask",
            description="--yes approves ask",
            tool="bash",
            args={"command": "echo safe"},
            expected_ci2lab="ask",
            expected_opencode={"yes_ask_bash": "allow"},
            expected_claude={"yes_ask_bash": "allow"},
            notes="auto_confirm turns ask->allow only in experimental",
        ),
        ComparisonCase(
            case_id="yes_not_deny",
            description="--yes does not bypass deny",
            tool="bash",
            args={"command": "rm *"},
            expected_ci2lab="deny",
            expected_opencode={"yes_ask_bash": "deny"},
            expected_claude={"yes_ask_bash": "deny", "default_experimental": "deny"},
        ),
    ]


def run_comparison(
    workspace: Path,
    *,
    outside_path: Path | None = None,
    env_path: Path | None = None,
    auto_confirm: bool = False,
    cases: list[ComparisonCase] | None = None,
) -> list[ComparisonRow]:
    """Run the comparison matrix across all engines and configs.

    Args:
        workspace: Path to the workspace root.
        outside_path: External file path; defaulted next to the workspace.
        env_path: ``.env`` file path; defaulted inside the workspace.
        auto_confirm: If True, ``ask`` resolves to ``allow`` where applicable.
        cases: Optional explicit cases; built by default.

    Returns:
        The evaluated comparison rows.
    """
    ws = workspace.resolve()
    outside = outside_path or (ws.parent / "outside" / "secret.txt")
    dotenv = env_path or (ws / ".env")
    if not dotenv.exists():
        dotenv.write_text("SECRET=1\n", encoding="utf-8")

    matrix = cases or build_comparison_cases(ws, outside, dotenv)
    rows: list[ComparisonRow] = []

    for case in matrix:
        ci2lab_cfg = AgentConfig(
            cwd=str(ws),
            security_engine="ci2lab",
            auto_confirm=auto_confirm,
        )
        (
            actual_ci2lab,
            matched_ci2lab,
            ext_ci2lab,
            hard_ci2lab,
            exp_ci2lab,
            _perm_ci2lab,
            _risk_ci2lab,
        ) = _gate_decision(case.tool, case.args, ci2lab_cfg)
        rows.append(
            ComparisonRow(
                case_id=case.case_id,
                description=case.description,
                engine="ci2lab",
                permission_config="hard_policy",
                tool=case.tool,
                target_or_command=target_label(case.args),
                expected_decision=case.expected_ci2lab,
                actual_decision=actual_ci2lab,
                matched_rule=matched_ci2lab,
                passed=actual_ci2lab == case.expected_ci2lab,
                notes=case.notes,
                external_directory=ext_ci2lab,
                hard_guards_enabled=hard_ci2lab,
                experimental=exp_ci2lab,
                risk_note=_risk_note_for_row(
                    engine="ci2lab",
                    case=case,
                    external_directory=ext_ci2lab,
                ),
            )
        )

        preset_keys = set(case.expected_opencode)
        if case.case_id == "yes_approves_ask":
            preset_keys.add("yes_ask_bash")
        for preset_key in sorted(preset_keys):
            rules = PERMISSION_PRESETS[preset_key]
            use_yes = case.case_id in {"yes_approves_ask", "yes_not_deny"}
            actual, matched, ext = _opencode_decision(
                case.tool,
                case.args,
                workspace=str(ws),
                rules=rules,
                auto_confirm=use_yes or auto_confirm,
            )
            expected = case.expected_opencode[preset_key]
            rows.append(
                ComparisonRow(
                    case_id=case.case_id,
                    description=case.description,
                    engine="opencode_experimental",
                    permission_config=preset_key,
                    tool=case.tool,
                    target_or_command=target_label(case.args),
                    expected_decision=expected,
                    actual_decision=actual,
                    matched_rule=matched,
                    passed=actual == expected,
                    notes=case.notes,
                    external_directory=ext,
                    hard_guards_enabled=False,
                    experimental=True,
                    risk_note=_risk_note_for_row(
                        engine="opencode_experimental",
                        case=case,
                        external_directory=ext,
                    ),
                )
            )

        claude_presets = set(case.expected_claude)
        if case.case_id == "yes_approves_ask":
            claude_presets.add("yes_ask_bash")
        for preset_key in sorted(claude_presets):
            if preset_key not in case.expected_claude:
                continue
            rules = PERMISSION_PRESETS[preset_key]
            use_yes = case.case_id in {"yes_approves_ask", "yes_not_deny"}
            claude_cfg = AgentConfig(
                cwd=str(ws),
                security_engine="ci2lab_guard",
                opencode_permissions=rules,
                auto_confirm=use_yes or auto_confirm,
            )
            (
                actual,
                matched,
                ext,
                hard,
                exp,
                perm_layer,
                gate_risk,
            ) = _gate_decision(case.tool, case.args, claude_cfg)
            expected = case.expected_claude[preset_key]
            risk = gate_risk or _risk_note_for_row(
                engine="ci2lab_guard",
                case=case,
                external_directory=ext,
            )
            rows.append(
                ComparisonRow(
                    case_id=case.case_id,
                    description=case.description,
                    engine="ci2lab_guard",
                    permission_config=preset_key,
                    tool=case.tool,
                    target_or_command=target_label(case.args),
                    expected_decision=expected,
                    actual_decision=actual,
                    matched_rule=matched,
                    passed=actual == expected,
                    notes=case.notes,
                    external_directory=ext,
                    hard_guards_enabled=hard,
                    experimental=exp,
                    risk_note=risk or "",
                    permission_layer_enabled=perm_layer,
                )
            )

    return rows


def row_to_dict(row: ComparisonRow) -> dict[str, Any]:
    """Serialize a :class:`ComparisonRow` to a flat dict for CSV/JSON output."""
    return {
        "case_id": row.case_id,
        "description": row.description,
        "engine": row.engine,
        "permission_config_name": row.permission_config,
        "tool": row.tool,
        "target_or_command": row.target_or_command,
        "expected_decision": row.expected_decision,
        "actual_decision": row.actual_decision,
        "matched_rule": row.matched_rule or "",
        "external_directory": row.external_directory,
        "hard_guards_enabled": row.hard_guards_enabled,
        "experimental": row.experimental,
        "passed": row.passed,
        "risk_note": row.risk_note,
    }


def format_comparison_table(rows: list[ComparisonRow]) -> str:
    """Render the comparison rows as a plain-text aligned table."""
    headers = [
        "case_id",
        "description",
        "engine",
        "permission_config",
        "tool",
        "target_or_command",
        "expected_decision",
        "actual_decision",
        "matched_rule",
        "passed",
        "notes",
    ]
    col_widths = {h: len(h) for h in headers}
    str_rows: list[dict[str, str]] = []
    for row in rows:
        data = {
            "case_id": row.case_id,
            "description": row.description[:40],
            "engine": row.engine,
            "permission_config": row.permission_config,
            "tool": row.tool,
            "target_or_command": row.target_or_command[:50],
            "expected_decision": row.expected_decision,
            "actual_decision": row.actual_decision,
            "matched_rule": row.matched_rule or "",
            "passed": "PASS" if row.passed else "FAIL",
            "notes": row.notes[:30],
        }
        str_rows.append(data)
        for key, value in data.items():
            col_widths[key] = max(col_widths[key], len(value))

    def fmt_line(values: dict[str, str]) -> str:
        return " | ".join(values[h].ljust(col_widths[h]) for h in headers)

    lines = [
        fmt_line({h: h for h in headers}),
        fmt_line({h: "-" * col_widths[h] for h in headers}),
    ]
    lines.extend(fmt_line(r) for r in str_rows)
    passed = sum(1 for r in rows if r.passed)
    lines.append("")
    lines.append(f"Summary: {passed}/{len(rows)} passed")
    return "\n".join(lines)


def format_comparison_markdown(rows: list[ComparisonRow], *, generated_at: str) -> str:
    """Render the comparison rows as a Markdown report.

    Args:
        rows: Evaluated comparison rows.
        generated_at: Timestamp string shown in the report header.

    Returns:
        The Markdown document as a string.
    """
    passed = sum(1 for r in rows if r.passed)
    lines = [
        "# Security engine comparison",
        "",
        f"Generated: {generated_at}",
        "",
        f"**Summary:** {passed}/{len(rows)} passed",
        "",
        "| " + " | ".join(_CSV_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in _CSV_COLUMNS) + " |",
    ]
    for row in rows:
        data = row_to_dict(row)
        cells = [str(data[c]).replace("|", "\\|").replace("\n", " ") for c in _CSV_COLUMNS]
        cells[-2] = "PASS" if row.passed else "FAIL"
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ComparisonExportResult:
    """Paths produced when exporting a comparison report.

    Attributes:
        output_dir: Directory containing the exported artifacts.
        csv_path: Path to the CSV report.
        markdown_path: Path to the Markdown report.
        ci2lab_config_path: Path to the ci2lab config snapshot.
        opencode_config_path: Path to the opencode config snapshot.
    """

    output_dir: Path
    csv_path: Path
    markdown_path: Path
    ci2lab_config_path: Path
    opencode_config_path: Path


def export_comparison_report(
    rows: list[ComparisonRow],
    *,
    workspace: Path,
    runs_dir: str = "runs",
) -> ComparisonExportResult:
    """Write CSV, Markdown and config snapshots under runs/security_comparison/."""
    ws = workspace.resolve()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    out_dir = ws / runs_dir / "security_comparison" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "comparison.csv"
    md_path = out_dir / "comparison.md"
    ci2lab_cfg_path = out_dir / "config_ci2lab.json"
    opencode_cfg_path = out_dir / "config_opencode_experimental.json"

    dict_rows = [row_to_dict(r) for r in rows]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for data in dict_rows:
            row_copy = dict(data)
            row_copy["passed"] = "PASS" if data["passed"] else "FAIL"
            writer.writerow(row_copy)

    generated_at = datetime.now(UTC).isoformat()
    md_path.write_text(
        format_comparison_markdown(rows, generated_at=generated_at),
        encoding="utf-8",
    )

    ci2lab_snapshot = {
        "engine": "ci2lab",
        "description": "Secure default engine (sandbox-first)",
        "security_profile": "standard",
        "hard_guards": {
            "workspace_confinement": True,
            "secret_policy": True,
            "bash_blocklist": True,
            "security_profiles": True,
        },
        "note": "root-level permission does not affect this engine",
    }
    opencode_snapshot = {
        "engine": "opencode_experimental",
        "description": "UNSAFE - replicates OpenCode allow/ask/deny for comparison",
        "permission": OpenCodePermissionConfig.default_experimental().rules,
        "permission_sources": {
            "precedence": [
                "security.permission",
                "permission (root-level)",
                "built-in defaults",
            ],
            "applies_only_to": "opencode_experimental",
        },
    }
    ci2lab_cfg_path.write_text(
        json.dumps(ci2lab_snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    opencode_cfg_path.write_text(
        json.dumps(opencode_snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return ComparisonExportResult(
        output_dir=out_dir,
        csv_path=csv_path,
        markdown_path=md_path,
        ci2lab_config_path=ci2lab_cfg_path,
        opencode_config_path=opencode_cfg_path,
    )
