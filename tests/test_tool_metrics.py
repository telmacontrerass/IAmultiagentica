"""Tests for the tool-call correctness KPI (ci2lab side and opencode side)."""

from __future__ import annotations

import json
from pathlib import Path

from ci2lab.bench.opencode_trace import (
    summarize_opencode_trace,
    summarize_opencode_trace_file,
)
from ci2lab.harness.parsing import detect_unknown_tool_attempt
from ci2lab.harness.run_logger import ToolCallLogEntry, ToolParseFailureEntry
from ci2lab.harness.tool_metrics import summarize_tool_calls


def _call(
    *,
    ok: bool = True,
    outcome: str | None = "approved",
    repaired: bool = False,
) -> ToolCallLogEntry:
    return ToolCallLogEntry(
        round=1,
        tool_call_id="c1",
        tool="read_file",
        arguments={},
        started_at="",
        ended_at="",
        duration_ms=0,
        ok=ok,
        output="",
        outcome=outcome,
        repaired=repaired,
    )


def test_clean_run_is_fully_correct() -> None:
    quality = summarize_tool_calls([_call(), _call()], [])
    assert quality.attempts == 2
    assert quality.raw_correct == 2
    assert quality.effective_correct == 2
    assert quality.raw_correctness_rate == 1.0
    assert quality.repair_rate == 0.0


def test_malformed_attempts_enter_the_denominator() -> None:
    # The whole point: an unparseable attempt never reaches record_tool_call, so
    # without the parse-failure rows it would be invisible and the rate would be
    # a flattering 100%.
    quality = summarize_tool_calls(
        [_call()],
        [ToolParseFailureEntry(round=1, kind="unparsed", excerpt="{bad json")],
    )
    assert quality.attempts == 2
    assert quality.malformed == 1
    assert quality.raw_correct == 1
    assert quality.raw_correctness_rate == 0.5


def test_hallucinated_tool_counts_as_a_failure() -> None:
    quality = summarize_tool_calls(
        [_call(ok=False, outcome="unknown_tool")],
        [ToolParseFailureEntry(round=2, kind="unknown_tool", tool="make_coffee", excerpt="")],
    )
    assert quality.attempts == 2
    assert quality.hallucinated_tool == 2
    assert quality.raw_correct == 0
    assert quality.effective_correct == 0


def test_repaired_call_is_effective_but_not_raw() -> None:
    # The harness fixed what the model got wrong: it ran, but it is not a model
    # success. This gap is the scaffolding's contribution.
    quality = summarize_tool_calls([_call(repaired=True)], [])
    assert quality.attempts == 1
    assert quality.repaired == 1
    assert quality.effective_correct == 1
    assert quality.raw_correct == 0
    assert quality.raw_correctness_rate == 0.0
    assert quality.effective_correctness_rate == 1.0
    assert quality.repair_rate == 1.0


def test_invalid_arguments_are_not_correct() -> None:
    quality = summarize_tool_calls([_call(ok=False, outcome="invalid_arguments")], [])
    assert quality.invalid_arguments == 1
    assert quality.effective_correct == 0


def test_execution_error_is_still_a_correct_call() -> None:
    # The model named a real tool with valid args; the tool failed for its own
    # reasons (missing file, failing command). That is not a tool-calling error.
    quality = summarize_tool_calls([_call(ok=False, outcome="command_failed")], [])
    assert quality.attempts == 1
    assert quality.effective_correct == 1
    assert quality.raw_correct == 1
    assert quality.execution_error == 1


def test_harness_synthesized_results_are_excluded_from_the_denominator() -> None:
    # The model did not emit these; counting them would corrupt the rate.
    entries = [
        _call(outcome="already_satisfied"),
        _call(ok=False, outcome="skipped_after_error"),
        _call(ok=False, outcome="repeated_failure"),
        _call(),
    ]
    quality = summarize_tool_calls(entries, [])
    assert quality.attempts == 1
    assert quality.raw_correctness_rate == 1.0


def test_empty_run_has_no_rate() -> None:
    quality = summarize_tool_calls([], [])
    assert quality.attempts == 0
    assert quality.raw_correctness_rate is None
    assert quality.to_dict()["raw_correctness_rate"] is None


def test_detect_unknown_tool_attempt() -> None:
    assert detect_unknown_tool_attempt('{"name": "make_coffee", "args": {}}') == "make_coffee"
    # A real tool call must not be reported as unknown.
    assert detect_unknown_tool_attempt('{"name": "read_file", "path": "a.txt"}') is None
    assert detect_unknown_tool_attempt("just prose, no tool call") is None


def _tool_use(status: str, error: str | None = None) -> dict[str, object]:
    state: dict[str, object] = {"status": status, "input": {}}
    if error is not None:
        state["error"] = error
    return {"type": "tool_use", "part": {"tool": "bash", "state": state}}


def test_opencode_trace_maps_onto_the_same_metric() -> None:
    events = [
        {"type": "step_start"},
        _tool_use("completed"),
        _tool_use("error", "Unknown tool: make_coffee"),
        _tool_use("error", "Invalid tool input: missing 'command'"),
        _tool_use("error", "exit status 1"),
        {"type": "text"},
    ]
    quality = summarize_opencode_trace(events)
    assert quality.attempts == 4
    assert quality.hallucinated_tool == 1
    assert quality.invalid_arguments == 1
    assert quality.execution_error == 1
    # completed + the failed-but-well-formed call
    assert quality.effective_correct == 2
    # opencode does not repair payloads, so raw == effective.
    assert quality.raw_correct == quality.effective_correct
    assert quality.repaired == 0


def test_opencode_trace_file_skips_partial_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.ndjson"
    path.write_text(
        json.dumps(_tool_use("completed")) + "\n" + '{"type": "tool_use", "par',
        encoding="utf-8",
    )
    quality = summarize_opencode_trace_file(path)
    assert quality is not None
    assert quality.attempts == 1
    assert quality.raw_correct == 1


def test_opencode_trace_file_missing_returns_none(tmp_path: Path) -> None:
    assert summarize_opencode_trace_file(tmp_path / "nope.ndjson") is None
