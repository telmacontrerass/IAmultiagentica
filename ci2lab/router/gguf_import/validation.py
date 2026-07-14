"""Deterministic isolated validation against llama.cpp's OpenAI-compatible API."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ci2lab.router.gguf_import.inspector import GGUFInspection, inspect_gguf
from ci2lab.router.gguf_import.source import GGUFSourceResolver
from ci2lab.runtime.llama_cpp import LlamaCppRuntime


@dataclass
class ValidationGates:
    process_started: bool = False
    health_check_ok: bool = False
    model_visible: bool = False
    normal_chat_valid: bool = False
    tools_in_prompt: bool | None = None
    tool_call_count: int = 0
    tool_name: str | None = None
    arguments_json_valid: bool = False
    tool_executed: bool = False
    observation_reinjected: bool = False
    final_response_present: bool = False
    final_state: str = "failed"
    rounds: int = 0
    duration_seconds: float = 0
    startup_duration_seconds: float = 0
    timeout: bool = False
    repeated_calls: bool = False
    http_errors: list[str] = field(default_factory=list)
    parser: str = "openai_native"
    protocol: str = "openai_chat_completions"


def _write(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _post(base_url: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object from llama-server")
    return result


def _get(base_url: str, path: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object from llama-server")
    return result


def create_run_dir(root: Path) -> Path:
    resolved_root = root.resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = (resolved_root / name).resolve()
    if resolved_root not in run_dir.parents:
        raise ValueError("Evidence path escapes the configured runs directory")
    run_dir.mkdir()
    _write(run_dir / "run_status.json", {"status": "initializing"})
    return run_dir


def _message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def validate_llama_cpp(
    model_path: Path,
    *,
    binary: str | Path | None,
    context_length: int,
    runs_root: Path,
    request_timeout: float = 120,
    startup_timeout: float = 120,
) -> tuple[Path, ValidationGates]:
    started = time.monotonic()
    run_dir = create_run_dir(runs_root)
    gates = ValidationGates()
    runtime: LlamaCppRuntime | None = None
    responses: dict[str, Any] = {}
    try:
        source = GGUFSourceResolver().resolve_local(model_path)
        inspection: GGUFInspection = inspect_gguf(model_path)
        _write(run_dir / "metadata.json", source.to_dict() | {"inspection": inspection.to_dict()})
        _write(run_dir / "template_analysis.json", asdict(inspection.template_analysis))
        if inspection.chat_template:
            (run_dir / "original_template.jinja").write_text(
                inspection.chat_template, encoding="utf-8", newline=""
            )
        runtime = LlamaCppRuntime(
            model_path,
            binary=binary,
            context_length=context_length,
            startup_timeout=startup_timeout,
            log_dir=run_dir,
        )
        version = subprocess.run(
            [str(runtime.binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        _write(
            run_dir / "runtime_version.json",
            {
                "argv": [str(runtime.binary), "--version"],
                "returncode": version.returncode,
                "stdout": version.stdout,
                "stderr": version.stderr,
            },
        )
        startup_started = time.monotonic()
        endpoint = runtime.start()
        gates.startup_duration_seconds = round(time.monotonic() - startup_started, 3)
        gates.process_started = runtime.was_started
        health = runtime.health_check()
        gates.health_check_ok = health.healthy
        health_payload = _get(endpoint.base_url.removesuffix("/v1"), "/health", request_timeout)
        models_payload = _get(endpoint.base_url, "/models", request_timeout)
        gates.model_visible = bool(models_payload.get("data"))
        _write(
            run_dir / "runtime_endpoints.json",
            {"health": health_payload, "models": models_payload},
        )
        normal = {
            "model": endpoint.model_id,
            "messages": [{"role": "user", "content": "Reply with exactly OK."}],
            "stream": False,
            "temperature": 0,
        }
        tool_request: dict[str, Any] = {
            "model": endpoint.model_id,
            "messages": [
                {"role": "user", "content": "Use add to calculate 2+3, then give the result."}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "add",
                        "description": "Add two integers",
                        "parameters": {
                            "type": "object",
                            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                            "required": ["a", "b"],
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "stream": False,
            "temperature": 0,
        }
        _write(run_dir / "request.json", {"normal": normal, "tool": tool_request})
        try:
            rendered = _post(
                endpoint.base_url.removesuffix("/v1"),
                "/apply-template",
                {
                    "messages": tool_request["messages"],
                    "tools": tool_request["tools"],
                    "add_generation_prompt": True,
                },
                request_timeout,
            )
            prompt = str(rendered.get("prompt") or rendered.get("content") or "")
            gates.tools_in_prompt = "add" in prompt and "properties" in prompt
            _write(run_dir / "prompt_rendering.json", {"available": True, "response": rendered})
            if prompt:
                (run_dir / "rendered_prompt.txt").write_text(prompt, encoding="utf-8")
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            _write(
                run_dir / "prompt_rendering.json",
                {"available": False, "error": str(exc)},
            )
        normal_response = _post(endpoint.base_url, "/chat/completions", normal, request_timeout)
        responses["normal"] = normal_response
        gates.rounds += 1
        gates.normal_chat_valid = bool(str(_message(normal_response).get("content") or "").strip())
        tool_response = _post(endpoint.base_url, "/chat/completions", tool_request, request_timeout)
        responses["tool_round_1"] = tool_response
        gates.rounds += 1
        assistant = _message(tool_response)
        raw_calls = assistant.get("tool_calls")
        calls: list[Any] = raw_calls if isinstance(raw_calls, list) else []
        gates.tool_call_count = len(calls)
        if calls and isinstance(calls[0], dict):
            raw_function = calls[0].get("function")
            function: dict[str, Any] = raw_function if isinstance(raw_function, dict) else {}
            gates.tool_name = str(function.get("name") or "") or None
            try:
                arguments = json.loads(str(function.get("arguments") or "{}"))
                gates.arguments_json_valid = isinstance(arguments, dict)
            except json.JSONDecodeError:
                arguments = {}
            if (
                gates.tool_name == "add"
                and gates.arguments_json_valid
                and set(arguments) >= {"a", "b"}
            ):
                result = int(arguments["a"]) + int(arguments["b"])
                gates.tool_executed = True
                call_id = str(calls[0].get("id") or "call_add")
                followup = dict(tool_request)
                followup["messages"] = [
                    *tool_request["messages"],
                    assistant,
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": "add",
                        "content": json.dumps({"result": result}),
                    },
                ]
                gates.observation_reinjected = True
                final = _post(endpoint.base_url, "/chat/completions", followup, request_timeout)
                responses["tool_round_2"] = final
                gates.rounds += 1
                final_message = _message(final)
                gates.final_response_present = bool(str(final_message.get("content") or "").strip())
                gates.repeated_calls = bool(final_message.get("tool_calls"))
        tools_passed = all(
            (
                gates.tool_executed,
                gates.observation_reinjected,
                gates.final_response_present,
                not gates.repeated_calls,
            )
        )
        gates.final_state = "passed" if tools_passed else "incompatible_tools"
    except TimeoutError as exc:
        gates.timeout = True
        gates.http_errors.append(str(exc))
    except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
        gates.http_errors.append(str(exc))
    finally:
        if runtime is not None:
            gates.process_started = gates.process_started or runtime.was_started
            runtime.stop()
        gates.duration_seconds = round(time.monotonic() - started, 3)
        if gates.final_state not in {"passed", "incompatible_tools"}:
            gates.final_state = "infrastructure_failed"
        _write(run_dir / "response.json", responses)
        _write(run_dir / "validation.json", asdict(gates))
        _write(
            run_dir / "run_status.json", {"status": "complete", "final_state": gates.final_state}
        )
        gate_lines = "\n".join(f"- {key}: `{value}`" for key, value in asdict(gates).items())
        (run_dir / "report.md").write_text(
            "# GGUF validation\n\n"
            "- Runtime: `llama.cpp`\n"
            "- Candidate: `llama_cpp_original_jinja`\n\n"
            "## Deterministic gates\n\n"
            f"{gate_lines}\n",
            encoding="utf-8",
        )
    return run_dir, gates
