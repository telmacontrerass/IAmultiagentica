"""Opt-in live robustness suite for a manifest-selected adapted GGUF protocol."""

from __future__ import annotations

import json
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ci2lab.router.gguf_import.adaptation import write_text_exact
from ci2lab.router.gguf_import.adapter_manifest import get_adapter
from ci2lab.router.gguf_import.inspector import inspect_gguf
from ci2lab.router.gguf_import.normalizer import build_reinjection, normalize_tool_call
from ci2lab.router.gguf_import.safe_tools import AdaptedRoundGuard, execute_validation_tool
from ci2lab.router.gguf_import.transforms import apply_template_transform
from ci2lab.router.gguf_import.validation import _message, _post, _write, create_run_dir
from ci2lab.runtime.llama_cpp import LlamaCppRuntime

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Return the supplied text exactly",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opaque_value",
            "description": "Generate an opaque runtime value from a seed",
            "parameters": {
                "type": "object",
                "properties": {"seed": {"type": "string"}},
                "required": ["seed"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_fixture",
            "description": "Read one controlled fixture by relative path",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "enum": ["fixture_secret.txt"]}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "always_fail",
            "description": "Always return a controlled error",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass
class RobustAttempt:
    scenario: str
    attempt: int
    expected_tool: str
    selected_tool: str | None = None
    schemas_rendered: bool = False
    call_detected: bool = False
    arguments_valid: bool = False
    tool_executed: bool = False
    observation_reinjected: bool = False
    observation_value: str | None = None
    final_response_present: bool = False
    final_response_uses_observation: bool = False
    repeated_call: bool = False
    rounds: int = 0
    latency_seconds: float = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    status: str = "failed"
    error: str | None = None


def _schemas() -> dict[str, dict[str, Any]]:
    return {str(item["function"]["name"]): item["function"]["parameters"] for item in TOOLS}


def _payload(model_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "stream": False,
        "temperature": 0,
        "max_tokens": 96,
    }


def _tokens(*responses: dict[str, Any]) -> tuple[int | None, int | None]:
    usages: list[dict[str, Any]] = []
    for response in responses:
        usage = response.get("usage")
        if isinstance(usage, dict):
            usages.append(usage)
    if not usages:
        return None, None
    return sum(int(item.get("prompt_tokens") or 0) for item in usages), sum(
        int(item.get("completion_tokens") or 0) for item in usages
    )


def _scenario_prompt(scenario: str, attempt: int) -> tuple[str, str]:
    if scenario == "opaque_value":
        return (
            "opaque_value",
            f"Use opaque_value with seed run-{attempt}. Return its exact value only after using the tool.",
        )
    if scenario == "read_fixture":
        return (
            "read_fixture",
            "Use read_fixture to read fixture_secret.txt. Return the exact content after using the tool.",
        )
    if scenario == "controlled_error":
        return (
            "always_fail",
            "Call always_fail with message benchmark. After the error, honestly explain that the tool failed.",
        )
    choices = (
        ("add", "Use add to calculate 17+29. You must use the correct tool."),
        ("echo", "Use echo with text SELECT_ECHO. You must use the correct tool."),
        ("opaque_value", f"Use opaque_value with seed selection-{attempt}."),
        ("read_fixture", "Use read_fixture to read fixture_secret.txt."),
        ("add", "Use add to calculate 31+11. You must use the correct tool."),
    )
    return choices[(attempt - 1) % len(choices)]


def _run_attempt(
    *,
    scenario: str,
    attempt: int,
    endpoint_url: str,
    model_id: str,
    manifest: Any,
    fixtures: Path,
    raw_dir: Path,
    observations: Path,
    schemas_rendered: bool,
    timeout: float,
) -> RobustAttempt:
    expected, prompt = _scenario_prompt(scenario, attempt)
    result = RobustAttempt(scenario, attempt, expected, schemas_rendered=schemas_rendered)
    started = time.monotonic()
    first_payload = _payload(model_id, [{"role": "user", "content": prompt}])
    first = _post(endpoint_url, "/chat/completions", first_payload, timeout)
    _write(raw_dir / f"{scenario}_{attempt}_round1.json", first)
    result.rounds = 1
    raw = str(_message(first).get("content") or "")
    call = normalize_tool_call(raw, tools=_schemas(), manifest=manifest)
    result.selected_tool = call.name
    result.call_detected = call.name is not None
    result.arguments_valid = call.executable
    if not call.executable or call.name != expected:
        result.error = call.rejection_reason or "wrong_tool"
        result.latency_seconds = round(time.monotonic() - started, 3)
        result.prompt_tokens, result.completion_tokens = _tokens(first)
        return result
    guard = AdaptedRoundGuard(max_rounds=3)
    accepted, reason = guard.accept(call)
    if not accepted:
        result.error = reason
        return result
    if scenario == "read_fixture" or (scenario == "selection" and expected == "read_fixture"):
        fixture_value = f"FILE_VALUE_{secrets.token_hex(12).upper()}"
        (fixtures / "fixture_secret.txt").write_text(fixture_value, encoding="utf-8")
    outcome = execute_validation_tool(call.name, call.arguments or {}, fixture_root=fixtures)
    result.tool_executed = True
    observation_value = (
        str(outcome.value)
        if outcome.ok
        else json.dumps({"ok": False, "error": outcome.error}, separators=(",", ":"))
    )
    result.observation_value = observation_value
    _write(
        observations / f"{scenario}_{attempt}.json",
        {"ok": outcome.ok, "value": outcome.value, "error": outcome.error},
    )
    assistant, observation = build_reinjection(call, observation_value, manifest)
    followup = _payload(model_id, [*first_payload["messages"], assistant, observation])
    final = _post(endpoint_url, "/chat/completions", followup, timeout)
    _write(raw_dir / f"{scenario}_{attempt}_round2.json", final)
    result.observation_reinjected = True
    result.rounds = 2
    final_text = str(_message(final).get("content") or "").strip()
    result.final_response_present = bool(final_text)
    repeated = normalize_tool_call(final_text, tools=_schemas(), manifest=manifest)
    result.repeated_call = repeated.executable
    if outcome.ok:
        result.final_response_uses_observation = observation_value in final_text
    else:
        lowered = final_text.lower()
        result.final_response_uses_observation = (
            any(word in lowered for word in ("error", "fail", "unable", "cannot"))
            and "success" not in lowered
        )
    result.prompt_tokens, result.completion_tokens = _tokens(first, final)
    result.latency_seconds = round(time.monotonic() - started, 3)
    result.status = (
        "passed"
        if all(
            (
                result.schemas_rendered,
                result.arguments_valid,
                result.tool_executed,
                result.observation_reinjected,
                result.final_response_present,
                result.final_response_uses_observation,
                not result.repeated_call,
            )
        )
        else "failed"
    )
    return result


def _negative_results(manifest: Any) -> list[dict[str, Any]]:
    cases = {
        "unknown_tool": "missing\n{}",
        "invalid_json": "add\nnot-json",
        "incomplete": 'add\n{"a":2}',
        "wrong_type": 'add\n{"a":"2","b":3}',
        "multiple_json": 'add\n{"a":2,"b":3}\n{"a":4,"b":5}',
        "prose_before": 'Before calling\nadd\n{"a":2,"b":3}',
    }
    output = []
    for name, raw in cases.items():
        call = normalize_tool_call(raw, tools=_schemas(), manifest=manifest)
        output.append({"id": name, "executable": call.executable, "reason": call.rejection_reason})
    exact = normalize_tool_call('add\n{"a":2,"b":3}', tools=_schemas(), manifest=manifest)
    guard = AdaptedRoundGuard(max_rounds=1)
    guard.accept(exact)
    repeat_accepted, repeat_reason = guard.accept(exact)
    output.append(
        {"id": "identical_repeat", "executable": repeat_accepted, "reason": repeat_reason}
    )
    other = normalize_tool_call('add\n{"a":4,"b":5}', tools=_schemas(), manifest=manifest)
    output.append(
        {
            "id": "round_limit",
            "executable": guard.accept(other)[0],
            "reason": guard.accept(other)[1],
        }
    )
    return output


def _run_two_sequential(
    *,
    endpoint_url: str,
    model_id: str,
    manifest: Any,
    fixtures: Path,
    raw_dir: Path,
    observations: Path,
    schemas_rendered: bool,
    timeout: float,
) -> RobustAttempt:
    result = RobustAttempt("two_sequential", 1, "opaque_value", schemas_rendered=schemas_rendered)
    started = time.monotonic()
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": "First call opaque_value with seed chain. After receiving its observation, call echo with exactly that opaque value. Only then provide the final echoed value.",
        }
    ]
    responses: list[dict[str, Any]] = []
    guard = AdaptedRoundGuard(max_rounds=3)
    opaque: str | None = None
    for round_number, expected in ((1, "opaque_value"), (2, "echo")):
        response = _post(endpoint_url, "/chat/completions", _payload(model_id, messages), timeout)
        responses.append(response)
        _write(raw_dir / f"two_sequential_1_round{round_number}.json", response)
        call = normalize_tool_call(
            str(_message(response).get("content") or ""), tools=_schemas(), manifest=manifest
        )
        if not call.executable or call.name != expected:
            result.selected_tool = call.name
            result.error = call.rejection_reason or f"expected_{expected}"
            result.rounds = round_number
            result.latency_seconds = round(time.monotonic() - started, 3)
            result.prompt_tokens, result.completion_tokens = _tokens(*responses)
            return result
        accepted, reason = guard.accept(call)
        if not accepted:
            result.error = reason
            return result
        if expected == "echo" and (call.arguments or {}).get("text") != opaque:
            result.error = "second_call_did_not_use_first_observation"
            return result
        outcome = execute_validation_tool(call.name, call.arguments or {}, fixture_root=fixtures)
        observation_value = str(outcome.value)
        if expected == "opaque_value":
            opaque = observation_value
        assistant, observation = build_reinjection(call, observation_value, manifest)
        messages.extend([assistant, observation])
        _write(
            observations / f"two_sequential_1_round{round_number}.json",
            {"tool": call.name, "value": observation_value},
        )
    final = _post(endpoint_url, "/chat/completions", _payload(model_id, messages), timeout)
    responses.append(final)
    _write(raw_dir / "two_sequential_1_round3.json", final)
    final_text = str(_message(final).get("content") or "").strip()
    repeated = normalize_tool_call(final_text, tools=_schemas(), manifest=manifest)
    result.selected_tool = "opaque_value,echo"
    result.call_detected = True
    result.arguments_valid = True
    result.tool_executed = True
    result.observation_reinjected = True
    result.observation_value = opaque
    result.final_response_present = bool(final_text)
    result.final_response_uses_observation = bool(opaque and opaque in final_text)
    result.repeated_call = repeated.executable
    result.rounds = 3
    result.prompt_tokens, result.completion_tokens = _tokens(*responses)
    result.latency_seconds = round(time.monotonic() - started, 3)
    result.status = (
        "passed"
        if result.final_response_present
        and result.final_response_uses_observation
        and not result.repeated_call
        else "failed"
    )
    return result


def run_robust_suite(
    model_path: Path,
    *,
    binary: Path,
    runs_root: Path,
    adapter_id: str,
    repetitions: int = 5,
    context_length: int = 16000,
    timeout: float = 180,
) -> tuple[Path, dict[str, Any]]:
    run_dir = create_run_dir(runs_root)
    fixtures, raw_dir, observations = (
        run_dir / name for name in ("fixtures", "raw_responses", "observations")
    )
    for directory in (fixtures, raw_dir, observations):
        directory.mkdir()
    manifest = get_adapter(adapter_id)
    inspection = inspect_gguf(model_path)
    if not manifest.matches(
        architecture=inspection.architecture or "",
        template_sha256=inspection.template_analysis.template_sha256 or "",
        runtime="llama.cpp",
    ):
        raise ValueError("Adapter does not strictly match the GGUF and runtime")
    transformed = apply_template_transform(inspection.chat_template or "", manifest)
    template_path = run_dir / "adapted_template.jinja"
    write_text_exact(template_path, transformed.adapted)
    _write(
        run_dir / "suite_manifest.json",
        {
            "adapter": manifest.to_dict(),
            "repetitions": repetitions,
            "scenarios": [
                "opaque_value",
                "read_fixture",
                "selection",
                "controlled_error",
                "two_sequential",
            ],
            "tools": TOOLS,
        },
    )
    runtime = LlamaCppRuntime(
        model_path,
        binary=binary,
        context_length=context_length,
        startup_timeout=120,
        log_dir=run_dir,
        template_path=template_path,
    )
    results: list[RobustAttempt] = []
    jsonl_path = run_dir / "scenario_results.jsonl"

    def record(item: RobustAttempt) -> None:
        results.append(item)
        with jsonl_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    try:
        version = subprocess.run(
            [str(runtime.binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if version.returncode or not manifest.runtime_version_compatible(
            version.stdout + version.stderr
        ):
            raise RuntimeError("Incompatible llama.cpp version")
        endpoint = runtime.start()
        apply_payload = {
            "messages": [{"role": "user", "content": "benchmark"}],
            "tools": TOOLS,
            "add_generation_prompt": True,
        }
        rendered = _post(
            endpoint.base_url.removesuffix("/v1"), "/apply-template", apply_payload, timeout
        )
        prompt = str(rendered.get("prompt") or "")
        schemas_rendered = all(str(item["function"]["name"]) in prompt for item in TOOLS)
        for scenario in ("opaque_value", "read_fixture", "selection", "controlled_error"):
            for attempt in range(1, repetitions + 1):
                try:
                    item = _run_attempt(
                        scenario=scenario,
                        attempt=attempt,
                        endpoint_url=endpoint.base_url,
                        model_id=endpoint.model_id,
                        manifest=manifest,
                        fixtures=fixtures,
                        raw_dir=raw_dir,
                        observations=observations,
                        schemas_rendered=schemas_rendered,
                        timeout=timeout,
                    )
                except Exception as exc:
                    expected, _prompt = _scenario_prompt(scenario, attempt)
                    item = RobustAttempt(
                        scenario,
                        attempt,
                        expected,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                record(item)
        try:
            sequential = _run_two_sequential(
                endpoint_url=endpoint.base_url,
                model_id=endpoint.model_id,
                manifest=manifest,
                fixtures=fixtures,
                raw_dir=raw_dir,
                observations=observations,
                schemas_rendered=schemas_rendered,
                timeout=timeout,
            )
        except Exception as exc:
            sequential = RobustAttempt(
                "two_sequential",
                1,
                "opaque_value,echo",
                error=f"{type(exc).__name__}: {exc}",
            )
        record(sequential)
    finally:
        runtime.stop()
    negatives = _negative_results(manifest)
    passed_by_scenario = {
        name: sum(item.status == "passed" for item in results if item.scenario == name)
        for name in ("opaque_value", "read_fixture", "selection", "controlled_error")
    }
    latencies = [item.latency_seconds for item in results]
    total = len(results)
    aggregate: dict[str, Any] = {
        "total_attempts": total,
        "valid_call_rate": sum(item.call_detected for item in results) / total,
        "valid_arguments_rate": sum(item.arguments_valid for item in results) / total,
        "execution_rate": sum(item.tool_executed for item in results) / total,
        "observation_use_rate": sum(item.final_response_uses_observation for item in results)
        / total,
        "finalization_rate": sum(item.final_response_present for item in results) / total,
        "repeat_rate": sum(item.repeated_call for item in results) / total,
        "latency_mean": sum(latencies) / total,
        "latency_min": min(latencies),
        "latency_max": max(latencies),
        "mean_rounds": sum(item.rounds for item in results) / total,
        "passed_by_scenario": passed_by_scenario,
        "negative_cases": negatives,
    }
    aggregate["robust_validation_passed"] = (
        all(value == repetitions for value in passed_by_scenario.values())
        and all(not item["executable"] for item in negatives)
        and not any(item.repeated_call for item in results)
    )
    _write(run_dir / "aggregate_results.json", aggregate)
    _write(
        run_dir / "comparison.json",
        {
            "fenced": {"status": "not_run", "latency": None, "tokens": None},
            "adapted_native": aggregate,
        },
    )
    (run_dir / "report.md").write_text(
        "# Robust adapted-tools benchmark\n\n"
        + "\n".join(f"- {key}: `{value}`" for key, value in aggregate.items())
        + "\n",
        encoding="utf-8",
    )
    _write(
        run_dir / "run_status.json",
        {
            "status": "complete",
            "robust_validation_passed": aggregate["robust_validation_passed"],
        },
    )
    return run_dir, aggregate
