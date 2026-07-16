"""Comparator of OpenCode configs against a case matrix (EXPERIMENTAL)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import evaluate_tool_gate
from ci2lab.security.gate_check import target_label
from ci2lab.security.opencode_config_io import (
    OpenCodeConfigBundle,
    bundle_from_preset,
    load_opencode_config_bundle,
)

_CONFIG_CSV_COLUMNS = [
    "case_id",
    "config_name",
    "tool",
    "target_or_command",
    "actual_decision",
    "matched_rule",
    "external_directory",
    "unsupported_tools",
    "warnings",
    "risk_note",
    "passed",
]


@dataclass
class ConfigComparisonRow:
    """One row comparing a config's decision for a single case.

    Attributes:
        case_id: Identifier of the source case.
        config_name: Name of the config being evaluated.
        tool: Tool name exercised.
        target_or_command: Target path or command label.
        actual_decision: Decision produced by the config.
        matched_rule: Rule that produced the decision, if any.
        external_directory: True if the target was outside the workspace.
        unsupported_tools: Comma-joined unsupported tool keys.
        warnings: Semicolon-joined config warnings.
        risk_note: Advisory risk note for the row.
        passed: True when the row is considered acceptable.
    """

    case_id: str
    config_name: str
    tool: str
    target_or_command: str
    actual_decision: str
    matched_rule: str | None
    external_directory: bool
    unsupported_tools: str
    warnings: str
    risk_note: str
    passed: bool = True


@dataclass(frozen=True)
class ConfigComparisonExportResult:
    """Paths produced when exporting a config-comparison report.

    Attributes:
        output_dir: Directory containing the exported artifacts.
        csv_path: Path to the CSV report.
        markdown_path: Path to the Markdown report.
    """

    output_dir: Path
    csv_path: Path
    markdown_path: Path


def build_config_comparison_cases(
    workspace: Path,
    outside_path: Path,
    env_path: Path,
) -> list[dict[str, Any]]:
    """Build the case matrix used to compare OpenCode configs.

    Args:
        workspace: Path to the workspace root.
        outside_path: External file path for external-access cases.
        env_path: ``.env`` file path for secret-policy cases.

    Returns:
        A list of case dicts, each with ``case_id``, ``tool`` and ``args``.
    """
    inside = workspace / "inside.txt"
    return [
        {
            "case_id": "read_internal",
            "tool": "read_file",
            "args": {"path": str(inside)},
        },
        {
            "case_id": "read_external",
            "tool": "read_file",
            "args": {"path": str(outside_path)},
        },
        {
            "case_id": "read_dotenv",
            "tool": "read_file",
            "args": {"path": str(env_path)},
        },
        {
            "case_id": "write_file",
            "tool": "write_file",
            "args": {"path": "new.txt", "content": "x"},
        },
        {
            "case_id": "edit_file",
            "tool": "edit_file",
            "args": {
                "path": str(inside),
                "old_string": "inside",
                "new_string": "inside2",
            },
        },
        {
            "case_id": "bash_git",
            "tool": "bash",
            "args": {"command": "git status"},
        },
        {
            "case_id": "bash_pytest",
            "tool": "bash",
            "args": {"command": "pytest --version"},
        },
        {
            "case_id": "bash_unknown",
            "tool": "bash",
            "args": {"command": "echo safe"},
        },
        {
            "case_id": "bash_rm",
            "tool": "bash",
            "args": {"command": "rm *"},
        },
        {
            "case_id": "tree_read_alias",
            "tool": "tree",
            "args": {"path": "."},
        },
        {
            "case_id": "grep_read_alias",
            "tool": "grep",
            "args": {"path": ".", "pattern": "inside"},
        },
    ]


def _risk_note_for_case(
    *,
    case_id: str,
    external_directory: bool,
    warnings: list[str],
) -> str:
    """Derive an advisory risk note for a config-comparison case."""
    if case_id == "read_external" and any("external_directory=allow" in w for w in warnings):
        return "UNSAFE: external read allowed by config"
    if external_directory and case_id == "read_external":
        return "external path evaluated with external_directory"
    return "; ".join(warnings) if warnings else ""


def run_config_comparison(
    bundles: list[tuple[str, OpenCodeConfigBundle]],
    workspace: Path,
    *,
    outside_path: Path | None = None,
    env_path: Path | None = None,
) -> list[ConfigComparisonRow]:
    """Evaluate each bundle against the case matrix and collect rows.

    Creates fixture files (``.env``, an external file and ``inside.txt``) if
    they do not already exist.

    Args:
        bundles: Named config bundles to compare.
        workspace: Path to the workspace root.
        outside_path: External file path; defaulted next to the workspace.
        env_path: ``.env`` file path; defaulted inside the workspace.

    Returns:
        The evaluated comparison rows.
    """
    ws = workspace.resolve()
    outside = outside_path or (ws.parent / "outside_cmp" / "secret.txt")
    dotenv = env_path or (ws / ".env")
    if not dotenv.exists():
        dotenv.write_text("SECRET=1\n", encoding="utf-8")
    if not outside.parent.exists():
        outside.parent.mkdir(parents=True, exist_ok=True)
    if not outside.exists():
        outside.write_text("outside\n", encoding="utf-8")
    if not (ws / "inside.txt").exists():
        (ws / "inside.txt").write_text("inside\n", encoding="utf-8")

    cases = build_config_comparison_cases(ws, outside, dotenv)
    rows: list[ConfigComparisonRow] = []

    for config_name, bundle in bundles:
        agent = AgentConfig(
            cwd=str(ws),
            security_engine="opencode_experimental",
            opencode_permissions=bundle.to_permission_config(),
        )
        warn_text = "; ".join(bundle.warnings)
        unsupported_text = ", ".join(bundle.unsupported_tools)
        for case in cases:
            tool = case["tool"]
            args = case["args"]
            gate = evaluate_tool_gate(tool, args, agent)
            if gate.blocked:
                decision = "deny"
            elif gate.needs_confirm:
                decision = "ask"
            else:
                decision = "allow"
            risk = _risk_note_for_case(
                case_id=case["case_id"],
                external_directory=gate.external_directory,
                warnings=bundle.warnings,
            )
            rows.append(
                ConfigComparisonRow(
                    case_id=case["case_id"],
                    config_name=config_name,
                    tool=tool,
                    target_or_command=target_label(args),
                    actual_decision=decision,
                    matched_rule=gate.matched_rule,
                    external_directory=gate.external_directory,
                    unsupported_tools=unsupported_text,
                    warnings=warn_text,
                    risk_note=risk,
                    passed=True,
                )
            )
    return rows


def resolve_config_bundles(
    *,
    config_paths: list[Path],
    presets: list[str],
) -> list[tuple[str, OpenCodeConfigBundle]]:
    """Resolve config files and presets into named bundles.

    Args:
        config_paths: Paths to JSON config files to load.
        presets: Names of built-in presets to include.

    Returns:
        A list of (name, bundle) pairs, files first then presets.
    """
    bundles: list[tuple[str, OpenCodeConfigBundle]] = []
    for path in config_paths:
        bundle = load_opencode_config_bundle(path)
        bundles.append((path.name, bundle))
    for preset in presets:
        bundles.append((f"preset:{preset}", bundle_from_preset(preset)))
    return bundles


def row_to_dict(row: ConfigComparisonRow) -> dict[str, Any]:
    """Serialize a :class:`ConfigComparisonRow` to a flat dict for output."""
    return {
        "case_id": row.case_id,
        "config_name": row.config_name,
        "tool": row.tool,
        "target_or_command": row.target_or_command,
        "actual_decision": row.actual_decision,
        "matched_rule": row.matched_rule or "",
        "external_directory": row.external_directory,
        "unsupported_tools": row.unsupported_tools,
        "warnings": row.warnings,
        "risk_note": row.risk_note,
        "passed": row.passed,
    }


def format_config_comparison_markdown(
    rows: list[ConfigComparisonRow],
    *,
    generated_at: str,
) -> str:
    """Render config-comparison rows as a Markdown table.

    Args:
        rows: Evaluated comparison rows.
        generated_at: Timestamp string shown in the header.

    Returns:
        The Markdown document as a string.
    """
    lines = [
        "# OpenCode config comparison",
        "",
        f"Generated: {generated_at}",
        "",
        f"**Rows:** {len(rows)}",
        "",
        "| " + " | ".join(_CONFIG_CSV_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in _CONFIG_CSV_COLUMNS) + " |",
    ]
    for row in rows:
        data = row_to_dict(row)
        cells = [str(data[c]).replace("|", "\\|").replace("\n", " ") for c in _CONFIG_CSV_COLUMNS]
        cells[-1] = "PASS" if row.passed else "FAIL"
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def export_config_comparison_report(
    rows: list[ConfigComparisonRow],
    *,
    workspace: Path,
    runs_dir: str = "runs",
) -> ConfigComparisonExportResult:
    """Write the config-comparison CSV and Markdown reports under ``runs``.

    Args:
        rows: Evaluated comparison rows.
        workspace: Path to the workspace root.
        runs_dir: Name of the runs directory under the workspace.

    Returns:
        A :class:`ConfigComparisonExportResult` with the written paths.
    """
    ws = workspace.resolve()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
    out_dir = ws / runs_dir / "opencode_config_comparison" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "comparison.csv"
    md_path = out_dir / "comparison.md"

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CONFIG_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            data = row_to_dict(row)
            data["passed"] = "PASS" if row.passed else "FAIL"
            writer.writerow(data)

    generated_at = datetime.now(UTC).isoformat()
    md_path.write_text(
        format_config_comparison_markdown(rows, generated_at=generated_at),
        encoding="utf-8",
    )
    return ConfigComparisonExportResult(
        output_dir=out_dir,
        csv_path=csv_path,
        markdown_path=md_path,
    )
