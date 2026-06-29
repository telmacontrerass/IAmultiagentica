"""P2.10 — Harness Write Reliability Eval (static oracles + live runner)."""

from __future__ import annotations

import ast
import csv
import difflib
import importlib.util
import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ci2lab.harness import default_selection, run_agent
from ci2lab.harness.parsing import looks_like_unparsed_tool_attempt
from ci2lab.harness.types import AgentConfig
from ci2lab.pipeline import prepare_session

PASS = "PASS"
FAIL_MODEL_UNDERSTANDING = "FAIL_MODEL_UNDERSTANDING"
FAIL_MODEL_TOOL_FORMAT = "FAIL_MODEL_TOOL_FORMAT"
FAIL_HARNESS_PATCH = "FAIL_HARNESS_PATCH"
FAIL_HARNESS_POLICY = "FAIL_HARNESS_POLICY"
FAIL_HARNESS_PATH = "FAIL_HARNESS_PATH"
FAIL_ENVIRONMENT = "FAIL_ENVIRONMENT"
FAIL_TEST_ORACLE = "FAIL_TEST_ORACLE"
UNKNOWN_FAIL = "UNKNOWN_FAIL"

ALL_VERDICTS = (
    PASS,
    FAIL_MODEL_UNDERSTANDING,
    FAIL_MODEL_TOOL_FORMAT,
    FAIL_HARNESS_PATCH,
    FAIL_HARNESS_POLICY,
    FAIL_HARNESS_PATH,
    FAIL_ENVIRONMENT,
    FAIL_TEST_ORACLE,
    UNKNOWN_FAIL,
)

DEFAULT_MODELS = ("llama3.1:8b", "qwen3:4b")

_EXCLUDE_SNAPSHOT_DIRS = frozenset({"runs", ".ci2lab", "__pycache__"})


@dataclass(frozen=True)
class HarnessWriteCaseSpec:
    """Immutable specification of one write-reliability test case."""

    case_id: str
    prompt: str
    fixtures: dict[str, str] = field(default_factory=dict)
    expects_outside_block: bool = False


@dataclass
class HarnessWriteCaseResult:
    """Outcome of running one write-reliability case against a model."""

    case_id: str
    model: str
    tool_mode: str
    prompt: str
    verdict: str
    oracle_ok: bool
    notes: str = ""
    exit_code: int = 0
    tool_call_count: int = 0
    write_tool_attempts: int = 0
    blocked_outcomes: list[str] = field(default_factory=list)
    outside_file_created: bool = False
    answer_preview: str = ""
    artifact_dir: str = ""


def default_live_cases() -> list[HarnessWriteCaseSpec]:
    """Return the default set of live write-reliability cases.

    Covers creating a file, an exact line edit, adding a function, editing JSON,
    and an out-of-workspace write that must be blocked by policy.
    """
    return [
        HarnessWriteCaseSpec(
            case_id="create_file_simple",
            # Keep the literal text "hola": the oracle checks the file contains it.
            prompt="Create hello.txt with exactly the text: hola",
        ),
        HarnessWriteCaseSpec(
            case_id="modify_exact_line",
            prompt='Change VERSION to "0.1.1" without touching anything else.',
            fixtures={"version.py": 'VERSION = "0.1.0"\n'},
        ),
        HarnessWriteCaseSpec(
            case_id="add_function",
            prompt="Add a function add(a, b) that returns a + b.",
            fixtures={"math_utils.py": "# math utils\n"},
        ),
        HarnessWriteCaseSpec(
            case_id="edit_json",
            prompt="Change enabled to true while keeping valid JSON.",
            fixtures={
                "config.json": json.dumps({"enabled": False, "threshold": 3}, indent=2) + "\n"
            },
        ),
        HarnessWriteCaseSpec(
            case_id="outside_workspace_block",
            # Keep the literal text "should_not_exist": the oracle relies on it.
            prompt=("Try to create ../outside.txt with write_file and text should_not_exist."),
            expects_outside_block=True,
        ),
    ]


def static_write_config(cwd: str | Path) -> AgentConfig:
    """Non-interactive AgentConfig for deterministic harness tests."""
    return AgentConfig(
        cwd=str(cwd),
        auto_confirm=True,
        require_diff_preview=False,
        write_tools_enabled=True,
        stream=False,
        run_log_enabled=False,
        security_engine="ci2lab",
        security_profile="standard",
        confirm_callback=lambda _t, _s: True,
    )


def render_directory_tree(root: Path) -> str:
    """Render the workspace's files as a newline-separated relative-path listing.

    Directories in :data:`_EXCLUDE_SNAPSHOT_DIRS` (runs, caches) are skipped.
    Returns a placeholder when the workspace is missing or empty.
    """
    if not root.is_dir():
        return "(missing workspace)"
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _EXCLUDE_SNAPSHOT_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        lines.append(rel)
    return "\n".join(lines) if lines else "(empty)"


def snapshot_workspace(root: Path) -> dict[str, str]:
    """Capture workspace file contents as a ``{relative_path: text}`` mapping.

    Excludes snapshot directories; binary or unreadable files are recorded as
    the literal ``"<binary>"``.
    """
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _EXCLUDE_SNAPSHOT_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            out[rel] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            out[rel] = "<binary>"
    return out


def compute_workspace_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Produce a unified-diff-style summary of changes between two snapshots.

    Args:
        before: Snapshot taken before the run (see :func:`snapshot_workspace`).
        after: Snapshot taken after the run.

    Returns:
        A textual diff, with explicit markers for added and deleted files, or
        ``"(no file changes)"`` when nothing changed.
    """
    keys = sorted(set(before) | set(after))
    chunks: list[str] = []
    for key in keys:
        old = before.get(key, "")
        new = after.get(key, "")
        if old == new:
            continue
        if key not in before:
            chunks.append(f"+++ new file: {key}\n{new}")
            continue
        if key not in after:
            chunks.append(f"--- deleted: {key}\n{old}")
            continue
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{key}",
            tofile=f"b/{key}",
            lineterm="",
        )
        text = "".join(diff)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip() or "(no file changes)"


def prepare_case_workspace(
    base_dir: Path,
    *,
    case_id: str,
    model: str,
    fixtures: dict[str, str],
) -> tuple[Path, Path]:
    """Create fresh workspace and out-of-workspace directories for a case.

    Existing directories from a prior run are removed first, then the fixture
    files are written into the workspace.

    Args:
        base_dir: Parent directory under which the dirs are created.
        case_id: Case identifier, used in the directory names.
        model: Model tag; sanitised for use in directory names.
        fixtures: ``{relative_path: content}`` files to seed the workspace.

    Returns:
        A ``(workspace_dir, outside_dir)`` tuple of resolved paths.
    """
    safe_model = model.replace(":", "_").replace("/", "_")
    ws = (base_dir / f"{case_id}__{safe_model}").resolve()
    outside = (base_dir / f"{case_id}__{safe_model}__outside").resolve()
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    if outside.exists():
        shutil.rmtree(outside, ignore_errors=True)
    ws.mkdir(parents=True)
    outside.mkdir(parents=True)
    for rel, content in fixtures.items():
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return ws, outside


def _outside_target(outside_dir: Path) -> Path:
    """Return the path of the forbidden out-of-workspace target file."""
    return outside_dir / "outside.txt"


def oracle_create_file_simple(ws: Path) -> tuple[bool, str]:
    """Check that ``hello.txt`` was created containing exactly ``hola``.

    Returns:
        A ``(passed, detail)`` tuple describing the outcome.
    """
    target = ws / "hello.txt"
    if not target.is_file():
        return False, "hello.txt does not exist"
    text = target.read_text(encoding="utf-8").strip()
    if text != "hola":
        return False, f"unexpected content: {text!r}"
    return True, "hello.txt contains hola"


def oracle_modify_exact_line(ws: Path) -> tuple[bool, str]:
    """Check that ``version.py`` was bumped from ``0.1.0`` to ``0.1.1``.

    Returns:
        A ``(passed, detail)`` tuple describing the outcome.
    """
    target = ws / "version.py"
    if not target.is_file():
        return False, "version.py does not exist"
    text = target.read_text(encoding="utf-8")
    if 'VERSION = "0.1.1"' not in text:
        return False, f"VERSION not updated: {text!r}"
    if 'VERSION = "0.1.0"' in text:
        return False, "VERSION 0.1.0 is still present"
    return True, "VERSION = 0.1.1"


def oracle_add_function(ws: Path) -> tuple[bool, str]:
    """Check that ``math_utils.py`` defines a working ``add(a, b)`` function.

    Verifies via AST that an ``add`` function exists, then imports the module
    and asserts ``add(2, 3) == 5``.

    Returns:
        A ``(passed, detail)`` tuple describing the outcome.
    """
    target = ws / "math_utils.py"
    if not target.is_file():
        return False, "math_utils.py does not exist"
    source = target.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"invalid syntax: {exc}"
    has_add = any(isinstance(node, ast.FunctionDef) and node.name == "add" for node in tree.body)
    if not has_add:
        return False, "no add() function"
    spec = importlib.util.spec_from_file_location("math_utils_eval", target)
    if spec is None or spec.loader is None:
        return False, "could not import math_utils"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        add_fn = getattr(module, "add", None)
        if not callable(add_fn):
            return False, "add is not callable"
        if add_fn(2, 3) != 5:
            return False, f"add(2,3) -> {add_fn(2, 3)!r}"
    except Exception as exc:
        return False, f"import/execution failed: {exc}"
    return True, "add function importable and working"


def oracle_edit_json(ws: Path) -> tuple[bool, str]:
    """Check that ``config.json`` set ``enabled`` to true while staying valid.

    Confirms the file parses as JSON, ``enabled`` is ``True``, and the unrelated
    ``threshold`` value was left untouched.

    Returns:
        A ``(passed, detail)`` tuple describing the outcome.
    """
    target = ws / "config.json"
    if not target.is_file():
        return False, "config.json does not exist"
    raw = target.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON: {exc}"
    if data.get("enabled") is not True:
        return False, f"enabled={data.get('enabled')!r}"
    if data.get("threshold") != 3:
        return False, f"threshold altered: {data.get('threshold')!r}"
    return True, "valid JSON with enabled=true"


def oracle_outside_workspace_block(ws: Path, outside_dir: Path) -> tuple[bool, str]:
    """Check that no file escaped the workspace into ``outside_dir``.

    Args:
        ws: The agent's workspace directory.
        outside_dir: The sibling directory that must remain untouched.

    Returns:
        A ``(passed, detail)`` tuple; passes only when no out-of-workspace file
        was created.
    """
    outside_file = _outside_target(outside_dir)
    if outside_file.is_file():
        return False, f"external file created: {outside_file}"
    inside_escape = ws.parent / "outside.txt"
    checks_workspace_parent = outside_dir.resolve() == ws.parent.resolve()
    if (
        checks_workspace_parent
        and inside_escape.is_file()
        and inside_escape.resolve() != (ws / "outside.txt").resolve()
    ):
        try:
            inside_escape.relative_to(ws)
        except ValueError:
            return False, f"file outside the workspace: {inside_escape}"
    return True, "no external file"


def run_case_oracle(case_id: str, ws: Path, outside_dir: Path | None = None) -> tuple[bool, str]:
    """Dispatch to the oracle matching ``case_id`` and grade the workspace.

    Args:
        case_id: Identifier selecting which oracle to run.
        ws: The agent's workspace directory.
        outside_dir: Sibling directory for the out-of-workspace case; defaults
            to ``ws.parent``.

    Returns:
        A ``(passed, detail)`` tuple; an unknown ``case_id`` returns a failure.
    """
    if case_id == "create_file_simple":
        return oracle_create_file_simple(ws)
    if case_id == "modify_exact_line":
        return oracle_modify_exact_line(ws)
    if case_id == "add_function":
        return oracle_add_function(ws)
    if case_id == "edit_json":
        return oracle_edit_json(ws)
    if case_id == "outside_workspace_block":
        return oracle_outside_workspace_block(ws, outside_dir or ws.parent)
    return False, f"unknown oracle: {case_id}"


def _load_latest_tool_calls(runs_dir: Path) -> list[dict[str, Any]]:
    """Load tool-call records from the most recent run that produced a log.

    Iterates run subdirectories newest-first and returns the parsed
    ``tool_calls.jsonl`` of the first one that has it; otherwise an empty list.
    """
    if not runs_dir.is_dir():
        return []
    run_dirs = sorted(
        (p for p in runs_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run_dir in run_dirs:
        path = run_dir / "tool_calls.jsonl"
        if not path.is_file():
            continue
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
    return []


def _resolve_tool_mode(model: str, tool_mode: str | None) -> str:
    """Return the explicit ``tool_mode`` or the model's default selection mode."""
    if tool_mode:
        return tool_mode
    _, selection = prepare_session("", force_model=model, pull=False)
    return selection.tool_mode


def _quiet_agent_config(ws: Path) -> AgentConfig:
    """Build a non-interactive, logged :class:`AgentConfig` for a live case."""
    return AgentConfig(
        cwd=str(ws),
        auto_confirm=True,
        require_diff_preview=False,
        write_tools_enabled=True,
        stream=False,
        run_log_enabled=True,
        runs_dir=str(ws / "runs"),
        max_rounds=8,
        security_engine="ci2lab",
        security_profile="standard",
        confirm_callback=lambda _t, _s: True,
    )


def _answer_suggests_tool_format_failure(answer: str) -> bool:
    """Heuristically detect a tool call the model emitted as plain text.

    True when the answer looks like an unparsed tool attempt, or contains a JSON
    code fence naming ``write_file``.
    """
    if looks_like_unparsed_tool_attempt(answer):
        return True
    lower = answer.lower()
    return "```json" in lower and '"name"' in lower and "write_file" in lower


def classify_live_verdict(
    *,
    case: HarnessWriteCaseSpec,
    oracle_ok: bool,
    oracle_detail: str,
    answer: str,
    tool_calls: list[dict[str, Any]],
    harness_error: str | None,
    timed_out: bool,
    outside_file_created: bool,
) -> tuple[str, str]:
    """Classify a live case into one of the ``*_VERDICT`` codes.

    Distinguishes model failures (misunderstanding, malformed tool format) from
    harness failures (patch, policy, path) and environment failures (timeout,
    connectivity), using the oracle result, recorded write/edit tool calls and
    any harness error.

    Args:
        case: The case specification (notably ``expects_outside_block``).
        oracle_ok: Whether the case oracle passed.
        oracle_detail: Human-readable oracle explanation.
        answer: The model's final answer text.
        tool_calls: Recorded tool-call entries from the run.
        harness_error: Harness/exception message, if any.
        timed_out: Whether the run exceeded its timeout.
        outside_file_created: Whether a file was created outside the workspace.

    Returns:
        A ``(verdict, notes)`` tuple where ``verdict`` is one of the module's
        verdict constants.
    """
    if timed_out:
        return FAIL_ENVIRONMENT, "Timeout waiting for the model's response"
    if harness_error:
        lower = harness_error.lower()
        if any(tok in lower for tok in ("connection", "ollama", "refused", "unreachable")):
            return FAIL_ENVIRONMENT, harness_error[:400]
        return FAIL_HARNESS_PATCH, harness_error[:400]

    write_tools = [t for t in tool_calls if t.get("tool") in {"write_file", "edit_file"}]
    blocked = [
        str(t.get("outcome", ""))
        for t in write_tools
        if not t.get("ok") or str(t.get("outcome", "")).startswith("blocked")
    ]
    path_blocked = any(
        o in {"blocked_by_workspace", "blocked_by_policy", "denied"} or "workspace" in o
        for o in blocked
    )

    if case.expects_outside_block:
        if outside_file_created:
            return FAIL_HARNESS_POLICY, "A file was created outside the workspace"
        if oracle_ok and (path_blocked or not write_tools):
            return PASS, oracle_detail
        if oracle_ok and write_tools and all(t.get("ok") for t in write_tools):
            return FAIL_HARNESS_POLICY, "write_file allowed outside the workspace"
        if not oracle_ok:
            return FAIL_HARNESS_PATH, oracle_detail
        if _answer_suggests_tool_format_failure(answer) and not write_tools:
            return FAIL_MODEL_TOOL_FORMAT, "Tool call in text, never executed"
        return FAIL_MODEL_UNDERSTANDING, oracle_detail

    if oracle_ok:
        return PASS, oracle_detail

    if not write_tools and _answer_suggests_tool_format_failure(answer):
        return FAIL_MODEL_TOOL_FORMAT, "Tool call in text, never executed"

    if not write_tools:
        return FAIL_MODEL_UNDERSTANDING, f"No write/edit executed; {oracle_detail}"

    if write_tools and all(t.get("ok") for t in write_tools):
        return FAIL_HARNESS_PATCH, f"Tool OK but oracle failed: {oracle_detail}"

    if blocked:
        # Verdict note only (display/reporting) — not the security wire-contract
        # message. The blocking detection elsewhere keeps the Spanish substring.
        return FAIL_HARNESS_POLICY, f"Blocked by policy: {blocked}; {oracle_detail}"

    return UNKNOWN_FAIL, oracle_detail


def run_live_case(
    *,
    case: HarnessWriteCaseSpec,
    model: str,
    workspace_tmp: Path,
    artifact_dir: Path,
    timeout_s: int = 180,
    tool_mode: str | None = None,
    run_agent_fn: Callable[..., str] = run_agent,
) -> HarnessWriteCaseResult:
    """Run one case live against a model, persist artifacts, and grade it.

    Prepares the workspace, runs the agent (under a timeout in a worker thread),
    snapshots before/after state, writes prompt/tree/diff/verdict artifacts, runs
    the oracle and classifies the verdict.

    Args:
        case: The case to run.
        model: Ollama model tag.
        workspace_tmp: Parent directory for the case workspace.
        artifact_dir: Directory where artifacts for this case are written.
        timeout_s: Maximum seconds to wait for the model.
        tool_mode: Explicit tool mode, or ``None`` to use the model default.
        run_agent_fn: Injectable agent runner (defaults to :func:`run_agent`).

    Returns:
        The graded :class:`HarnessWriteCaseResult`.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ws, outside = prepare_case_workspace(
        workspace_tmp,
        case_id=case.case_id,
        model=model,
        fixtures=case.fixtures,
    )
    resolved_tool_mode = _resolve_tool_mode(model, tool_mode)
    before_tree = render_directory_tree(ws)
    before_snap = snapshot_workspace(ws)

    (artifact_dir / "prompt.txt").write_text(case.prompt, encoding="utf-8")
    (artifact_dir / "before_tree.txt").write_text(before_tree, encoding="utf-8")

    from unittest.mock import patch

    cfg = _quiet_agent_config(ws)
    selection = default_selection(model, tool_mode=resolved_tool_mode)
    answer = ""
    harness_error: str | None = None
    timed_out = False
    exit_code = 0

    def _task() -> str:
        """Run the agent for this case and return its final answer."""
        return run_agent_fn(case.prompt, selection, config=cfg)

    try:
        with patch("ci2lab.console.console.print"):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_task)
                answer = future.result(timeout=timeout_s)
    except FuturesTimeoutError:
        timed_out = True
        exit_code = 124
    except Exception as exc:
        harness_error = str(exc)
        exit_code = 1

    (artifact_dir / "stdout.txt").write_text(answer, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(harness_error or "", encoding="utf-8")

    after_tree = render_directory_tree(ws)
    after_snap = snapshot_workspace(ws)
    diff_text = compute_workspace_diff(before_snap, after_snap)
    (artifact_dir / "after_tree.txt").write_text(after_tree, encoding="utf-8")
    (artifact_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    tool_calls = _load_latest_tool_calls(ws / "runs")
    write_tools = [t for t in tool_calls if t.get("tool") in {"write_file", "edit_file"}]
    blocked_outcomes = [str(t.get("outcome", "")) for t in write_tools if not t.get("ok")]
    outside_file = _outside_target(outside)
    outside_created = outside_file.is_file()

    oracle_ok, oracle_detail = run_case_oracle(case.case_id, ws, outside_dir=outside)
    verdict, notes = classify_live_verdict(
        case=case,
        oracle_ok=oracle_ok,
        oracle_detail=oracle_detail,
        answer=answer,
        tool_calls=tool_calls,
        harness_error=harness_error,
        timed_out=timed_out,
        outside_file_created=outside_created,
    )

    verdict_payload = {
        "case_id": case.case_id,
        "model": model,
        "tool_mode": resolved_tool_mode,
        "verdict": verdict,
        "oracle_ok": oracle_ok,
        "oracle_detail": oracle_detail,
        "notes": notes,
        "exit_code": exit_code,
        "tool_call_count": len(tool_calls),
        "write_tool_attempts": len(write_tools),
        "blocked_outcomes": blocked_outcomes,
        "outside_file_created": outside_created,
        "answer_preview": (answer or "")[:220],
    }
    (artifact_dir / "verdict.json").write_text(
        json.dumps(verdict_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    return HarnessWriteCaseResult(
        case_id=case.case_id,
        model=model,
        tool_mode=resolved_tool_mode,
        prompt=case.prompt,
        verdict=verdict,
        oracle_ok=oracle_ok,
        notes=notes,
        exit_code=exit_code,
        tool_call_count=len(tool_calls),
        write_tool_attempts=len(write_tools),
        blocked_outcomes=blocked_outcomes,
        outside_file_created=outside_created,
        answer_preview=(answer or "")[:220].replace("\n", " "),
        artifact_dir=str(artifact_dir),
    )


def export_run_report(
    results: list[HarnessWriteCaseResult],
    *,
    output_dir: Path,
    workspace_tmp: Path,
    models: list[str],
    timeout_seconds: int,
) -> dict[str, Path]:
    """Write JSON and CSV reports summarising a suite of case results.

    Args:
        results: The per-case results to report.
        output_dir: Directory to write ``summary.json`` and ``results.csv``.
        workspace_tmp: Workspace root, recorded in the summary.
        models: Models that were exercised, recorded in the summary.
        timeout_seconds: Per-case timeout, recorded in the summary.

    Returns:
        A mapping with ``"summary"`` and ``"csv"`` keys pointing at the written
        report files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    csv_path = output_dir / "results.csv"

    counts: dict[str, int] = dict.fromkeys(ALL_VERDICTS, 0)
    for row in results:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1

    model_fails = sum(
        1 for r in results if r.verdict in {FAIL_MODEL_UNDERSTANDING, FAIL_MODEL_TOOL_FORMAT}
    )
    harness_fails = sum(
        1
        for r in results
        if r.verdict
        in {
            FAIL_HARNESS_PATCH,
            FAIL_HARNESS_POLICY,
            FAIL_HARNESS_PATH,
        }
    )
    env_fails = sum(1 for r in results if r.verdict == FAIL_ENVIRONMENT)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace_tmp": str(workspace_tmp.resolve()),
        "output_dir": str(output_dir.resolve()),
        "models": models,
        "timeout_seconds": timeout_seconds,
        "counts": counts,
        "pattern_hint": {
            "model_likely": model_fails,
            "harness_likely": harness_fails,
            "environment_likely": env_fails,
            "pass": counts.get(PASS, 0),
        },
        "results": [asdict(r) for r in results],
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    fieldnames = [
        "case_id",
        "model",
        "tool_mode",
        "verdict",
        "oracle_ok",
        "notes",
        "exit_code",
        "tool_call_count",
        "write_tool_attempts",
        "outside_file_created",
        "artifact_dir",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            data = asdict(row)
            writer.writerow({k: data.get(k, "") for k in fieldnames})

    return {"summary": summary_path, "csv": csv_path}


def run_live_suite(
    *,
    models: list[str],
    workspace_tmp: Path,
    output_dir: Path,
    cases: list[HarnessWriteCaseSpec] | None = None,
    timeout_s: int = 180,
    tool_mode: str | None = None,
) -> list[HarnessWriteCaseResult]:
    """Run every case against every model, then export the suite report.

    Args:
        models: Ollama model tags to evaluate.
        workspace_tmp: Parent directory for per-case workspaces.
        output_dir: Directory for per-case artifacts and the suite report.
        cases: Cases to run; defaults to :func:`default_live_cases`.
        timeout_s: Per-case timeout in seconds.
        tool_mode: Explicit tool mode, or ``None`` to use each model's default.

    Returns:
        The list of per-case results across all models.
    """
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    case_list = cases or default_live_cases()
    results: list[HarnessWriteCaseResult] = []
    for model in models:
        for case in case_list:
            safe_model = model.replace(":", "_")
            artifact_dir = output_dir / f"{case.case_id}__{safe_model}"
            results.append(
                run_live_case(
                    case=case,
                    model=model,
                    workspace_tmp=workspace_tmp,
                    artifact_dir=artifact_dir,
                    timeout_s=timeout_s,
                    tool_mode=tool_mode,
                )
            )
    export_run_report(
        results,
        output_dir=output_dir,
        workspace_tmp=workspace_tmp,
        models=models,
        timeout_seconds=timeout_s,
    )
    return results
