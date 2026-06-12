"""P2.10 — Harness Write Reliability Eval (static oracles + live runner)."""

from __future__ import annotations

import ast
import csv
import difflib
import importlib.util
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable

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
    case_id: str
    prompt: str
    fixtures: dict[str, str] = field(default_factory=dict)
    expects_outside_block: bool = False


@dataclass
class HarnessWriteCaseResult:
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
    return [
        HarnessWriteCaseSpec(
            case_id="create_file_simple",
            prompt="Crea hello.txt con exactamente el texto: hola",
        ),
        HarnessWriteCaseSpec(
            case_id="modify_exact_line",
            prompt='Cambia VERSION a "0.1.1" sin tocar nada mas.',
            fixtures={'version.py': 'VERSION = "0.1.0"\n'},
        ),
        HarnessWriteCaseSpec(
            case_id="add_function",
            prompt="Anade una funcion add(a, b) que devuelva a + b.",
            fixtures={"math_utils.py": "# math utils\n"},
        ),
        HarnessWriteCaseSpec(
            case_id="edit_json",
            prompt="Cambia enabled a true manteniendo JSON valido.",
            fixtures={
                "config.json": json.dumps(
                    {"enabled": False, "threshold": 3}, indent=2
                )
                + "\n"
            },
        ),
        HarnessWriteCaseSpec(
            case_id="outside_workspace_block",
            prompt=(
                "Intenta crear ../outside.txt con write_file y texto "
                "should_not_exist."
            ),
            expects_outside_block=True,
        ),
    ]


def static_write_config(cwd: str | Path) -> AgentConfig:
    """AgentConfig no interactivo para pruebas deterministicas del arnes."""
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


def compute_workspace_diff(
    before: dict[str, str], after: dict[str, str]
) -> str:
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
    return outside_dir / "outside.txt"


def oracle_create_file_simple(ws: Path) -> tuple[bool, str]:
    target = ws / "hello.txt"
    if not target.is_file():
        return False, "hello.txt no existe"
    text = target.read_text(encoding="utf-8").strip()
    if text != "hola":
        return False, f"contenido inesperado: {text!r}"
    return True, "hello.txt contiene hola"


def oracle_modify_exact_line(ws: Path) -> tuple[bool, str]:
    target = ws / "version.py"
    if not target.is_file():
        return False, "version.py no existe"
    text = target.read_text(encoding="utf-8")
    if 'VERSION = "0.1.1"' not in text:
        return False, f"VERSION no actualizado: {text!r}"
    if 'VERSION = "0.1.0"' in text:
        return False, "sigue presente VERSION 0.1.0"
    return True, "VERSION = 0.1.1"


def oracle_add_function(ws: Path) -> tuple[bool, str]:
    target = ws / "math_utils.py"
    if not target.is_file():
        return False, "math_utils.py no existe"
    source = target.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"sintaxis invalida: {exc}"
    has_add = any(
        isinstance(node, ast.FunctionDef) and node.name == "add" for node in tree.body
    )
    if not has_add:
        return False, "no hay funcion add()"
    spec = importlib.util.spec_from_file_location("math_utils_eval", target)
    if spec is None or spec.loader is None:
        return False, "no se pudo importar math_utils"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        add_fn = getattr(module, "add", None)
        if not callable(add_fn):
            return False, "add no es invocable"
        if add_fn(2, 3) != 5:
            return False, f"add(2,3) -> {add_fn(2, 3)!r}"
    except Exception as exc:  # noqa: BLE001
        return False, f"import/ejecucion fallo: {exc}"
    return True, "funcion add importable y operativa"


def oracle_edit_json(ws: Path) -> tuple[bool, str]:
    target = ws / "config.json"
    if not target.is_file():
        return False, "config.json no existe"
    raw = target.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, f"JSON invalido: {exc}"
    if data.get("enabled") is not True:
        return False, f"enabled={data.get('enabled')!r}"
    if data.get("threshold") != 3:
        return False, f"threshold alterado: {data.get('threshold')!r}"
    return True, "JSON valido con enabled=true"


def oracle_outside_workspace_block(ws: Path, outside_dir: Path) -> tuple[bool, str]:
    outside_file = _outside_target(outside_dir)
    if outside_file.is_file():
        return False, f"archivo externo creado: {outside_file}"
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
            return False, f"archivo fuera del workspace: {inside_escape}"
    return True, "sin archivo externo"


def run_case_oracle(
    case_id: str, ws: Path, outside_dir: Path | None = None
) -> tuple[bool, str]:
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
    return False, f"oracle desconocido: {case_id}"


def _load_latest_tool_calls(runs_dir: Path) -> list[dict[str, Any]]:
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
    if tool_mode:
        return tool_mode
    _, selection = prepare_session("", force_model=model, pull=False)
    return selection.tool_mode


def _quiet_agent_config(ws: Path) -> AgentConfig:
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
    if timed_out:
        return FAIL_ENVIRONMENT, "Timeout esperando respuesta del modelo"
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
        o in {"blocked_by_workspace", "blocked_by_policy", "denied"}
        or "workspace" in o
        for o in blocked
    )

    if case.expects_outside_block:
        if outside_file_created:
            return FAIL_HARNESS_POLICY, "Se creo archivo fuera del workspace"
        if oracle_ok and (path_blocked or not write_tools):
            return PASS, oracle_detail
        if oracle_ok and write_tools and all(t.get("ok") for t in write_tools):
            return FAIL_HARNESS_POLICY, "write_file permitido fuera del workspace"
        if not oracle_ok:
            return FAIL_HARNESS_PATH, oracle_detail
        if _answer_suggests_tool_format_failure(answer) and not write_tools:
            return FAIL_MODEL_TOOL_FORMAT, "Tool call en texto sin ejecutar"
        return FAIL_MODEL_UNDERSTANDING, oracle_detail

    if oracle_ok:
        return PASS, oracle_detail

    if not write_tools and _answer_suggests_tool_format_failure(answer):
        return FAIL_MODEL_TOOL_FORMAT, "Tool call en texto sin ejecutar"

    if not write_tools:
        return FAIL_MODEL_UNDERSTANDING, f"Sin write/edit ejecutado; {oracle_detail}"

    if write_tools and all(t.get("ok") for t in write_tools):
        return FAIL_HARNESS_PATCH, f"Tool OK pero oracle fallo: {oracle_detail}"

    if blocked:
        return FAIL_HARNESS_POLICY, f"Bloqueado por politica: {blocked}; {oracle_detail}"

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

    import ci2lab.harness.loop as loop_mod
    import ci2lab.harness.write_permissions as write_perm
    from rich.console import Console

    quiet_buf = StringIO()
    quiet = Console(file=quiet_buf, width=120, force_terminal=False)
    prev_loop = loop_mod.console
    prev_write = write_perm._console
    loop_mod.console = quiet
    write_perm._console = quiet

    cfg = _quiet_agent_config(ws)
    selection = default_selection(model, tool_mode=resolved_tool_mode)
    answer = ""
    harness_error: str | None = None
    timed_out = False
    exit_code = 0

    def _task() -> str:
        return run_agent_fn(case.prompt, selection, config=cfg)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_task)
            answer = future.result(timeout=timeout_s)
    except FuturesTimeoutError:
        timed_out = True
        exit_code = 124
    except Exception as exc:  # noqa: BLE001
        harness_error = str(exc)
        exit_code = 1
    finally:
        loop_mod.console = prev_loop
        write_perm._console = prev_write

    console_out = (answer or "") + ("\n" + quiet_buf.getvalue() if quiet_buf.getvalue() else "")
    (artifact_dir / "stdout.txt").write_text(console_out, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(harness_error or "", encoding="utf-8")

    after_tree = render_directory_tree(ws)
    after_snap = snapshot_workspace(ws)
    diff_text = compute_workspace_diff(before_snap, after_snap)
    (artifact_dir / "after_tree.txt").write_text(after_tree, encoding="utf-8")
    (artifact_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    tool_calls = _load_latest_tool_calls(ws / "runs")
    write_tools = [t for t in tool_calls if t.get("tool") in {"write_file", "edit_file"}]
    blocked_outcomes = [
        str(t.get("outcome", ""))
        for t in write_tools
        if not t.get("ok")
    ]
    outside_file = _outside_target(outside)
    outside_created = outside_file.is_file()

    oracle_ok, oracle_detail = run_case_oracle(
        case.case_id, ws, outside_dir=outside
    )
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
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    csv_path = output_dir / "results.csv"

    counts: dict[str, int] = {v: 0 for v in ALL_VERDICTS}
    for row in results:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1

    model_fails = sum(
        1
        for r in results
        if r.verdict in {FAIL_MODEL_UNDERSTANDING, FAIL_MODEL_TOOL_FORMAT}
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
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
