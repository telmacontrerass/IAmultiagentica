"""Comparador de configs OpenCode contra matriz de casos (EXPERIMENTAL)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ci2lab.harness.types import AgentConfig
from ci2lab.security.engine import evaluate_tool_gate
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
    output_dir: Path
    csv_path: Path
    markdown_path: Path


def build_config_comparison_cases(
    workspace: Path,
    outside_path: Path,
    env_path: Path,
) -> list[dict[str, Any]]:
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


def _target_label(args: dict[str, Any]) -> str:
    if "command" in args:
        return str(args["command"])
    if "path" in args:
        return str(args["path"])
    return str(args)[:120]


def _risk_note_for_case(
    *,
    case_id: str,
    external_directory: bool,
    warnings: list[str],
) -> str:
    if case_id == "read_external" and any(
        "external_directory=allow" in w for w in warnings
    ):
        return "INSEGURO: lectura externa permitida por config"
    if external_directory and case_id == "read_external":
        return "path externo evaluado con external_directory"
    return "; ".join(warnings) if warnings else ""


def run_config_comparison(
    bundles: list[tuple[str, OpenCodeConfigBundle]],
    workspace: Path,
    *,
    outside_path: Path | None = None,
    env_path: Path | None = None,
) -> list[ConfigComparisonRow]:
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
                    target_or_command=_target_label(args),
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
    bundles: list[tuple[str, OpenCodeConfigBundle]] = []
    for path in config_paths:
        bundle = load_opencode_config_bundle(path)
        bundles.append((path.name, bundle))
    for preset in presets:
        bundles.append((f"preset:{preset}", bundle_from_preset(preset)))
    return bundles


def row_to_dict(row: ConfigComparisonRow) -> dict[str, Any]:
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
        cells = [
            str(data[c]).replace("|", "\\|").replace("\n", " ")
            for c in _CONFIG_CSV_COLUMNS
        ]
        cells[-1] = "PASS" if row.passed else "FAIL"
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def export_config_comparison_report(
    rows: list[ConfigComparisonRow],
    *,
    workspace: Path,
    runs_dir: str = "runs",
) -> ConfigComparisonExportResult:
    ws = workspace.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
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

    generated_at = datetime.now(timezone.utc).isoformat()
    md_path.write_text(
        format_config_comparison_markdown(rows, generated_at=generated_at),
        encoding="utf-8",
    )
    return ConfigComparisonExportResult(
        output_dir=out_dir,
        csv_path=csv_path,
        markdown_path=md_path,
    )
