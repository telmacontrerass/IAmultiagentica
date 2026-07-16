"""Isolated validation of the explicitly adapted GLM GGUF Jinja candidate."""

from __future__ import annotations

import subprocess
import time
import urllib.error
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.router.gguf_import.adaptation import write_text_exact
from ci2lab.router.gguf_import.adapter_manifest import get_adapter
from ci2lab.router.gguf_import.inspector import inspect_gguf
from ci2lab.router.gguf_import.normalizer import build_reinjection, normalize_tool_call
from ci2lab.router.gguf_import.transforms import apply_template_transform
from ci2lab.router.gguf_import.validation import _get, _message, _post, _write, create_run_dir
from ci2lab.runtime.llama_cpp import LlamaCppRuntime


@dataclass
class AdaptedValidationGates:
    process_started: bool = False
    health_check_ok: bool = False
    model_visible: bool = False
    adapted_template_loaded: bool = False
    tool_name_in_prompt: bool = False
    tool_description_in_prompt: bool = False
    tool_parameters_in_prompt: bool = False
    raw_protocol_detected: str | None = None
    tool_name_source: str | None = None
    arguments_source: str | None = None
    normalization_possible: bool = False
    arguments_json_valid: bool = False
    tool_executed: bool = False
    observation_reinjected: bool = False
    final_response_present: bool = False
    repeated_call: bool = False
    rounds: int = 0
    startup_duration_seconds: float = 0
    duration_seconds: float = 0
    timeout: bool = False
    http_errors: list[str] = field(default_factory=list)
    final_state: str = "infrastructure_failed"


def _tool_payload(model_id: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": "Use add to calculate 2+3. You must call the tool and then give the result.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two integers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "stream": False,
        "temperature": 0,
    }


def validate_adapted_glm(
    model_path: Path,
    *,
    binary: Path,
    runs_root: Path,
    context_length: int = 16000,
    startup_timeout: float = 120,
    request_timeout: float = 180,
) -> tuple[Path, AdaptedValidationGates]:
    started = time.monotonic()
    run_dir = create_run_dir(runs_root)
    adaptation_dir = run_dir / "adaptation"
    adaptation_dir.mkdir()
    gates = AdaptedValidationGates()
    runtime: LlamaCppRuntime | None = None
    responses: dict[str, Any] = {}
    try:
        inspection = inspect_gguf(model_path)
        if not inspection.chat_template:
            raise ValueError("GGUF has no chat template")
        manifest = get_adapter("experimental_glm_global_tools_v1")
        if not manifest.matches(
            architecture=inspection.architecture or "",
            template_sha256=inspection.template_analysis.template_sha256 or "",
            runtime="llama.cpp",
        ):
            raise ValueError("Adapter does not match architecture, template hash and runtime")
        transformed = apply_template_transform(inspection.chat_template, manifest)
        original_path = adaptation_dir / "original_template.jinja"
        adapted_path = adaptation_dir / "adapted_template.jinja"
        write_text_exact(original_path, inspection.chat_template)
        write_text_exact(adapted_path, transformed.adapted)
        write_text_exact(adaptation_dir / "template.diff", transformed.diff)
        _write(
            adaptation_dir / "adaptation_manifest.json",
            manifest.to_dict()
            | {
                "original_template_sha256": transformed.original_sha256,
                "adapted_template_sha256": transformed.adapted_sha256,
            },
        )
        runtime = LlamaCppRuntime(
            model_path,
            binary=binary,
            context_length=context_length,
            startup_timeout=startup_timeout,
            log_dir=run_dir,
            template_path=adapted_path,
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
            {"returncode": version.returncode, "stdout": version.stdout, "stderr": version.stderr},
        )
        if version.returncode or not manifest.runtime_version_compatible(
            version.stdout + version.stderr
        ):
            raise RuntimeError("llama.cpp version does not satisfy the adapter manifest")
        startup_started = time.monotonic()
        endpoint = runtime.start()
        gates.startup_duration_seconds = round(time.monotonic() - startup_started, 3)
        gates.process_started = runtime.was_started
        health = runtime.health_check()
        gates.health_check_ok = health.healthy
        models = _get(endpoint.base_url, "/models", request_timeout)
        gates.model_visible = bool(models.get("data"))
        _write(
            run_dir / "runtime_endpoints.json",
            {
                "health": _get(endpoint.base_url.removesuffix("/v1"), "/health", request_timeout),
                "models": models,
            },
        )
        payload = _tool_payload(endpoint.model_id)
        apply_request = {
            "messages": payload["messages"],
            "tools": payload["tools"],
            "add_generation_prompt": True,
        }
        _write(adaptation_dir / "apply_template_request.json", apply_request)
        rendered_response = _post(
            endpoint.base_url.removesuffix("/v1"),
            "/apply-template",
            apply_request,
            request_timeout,
        )
        prompt = str(rendered_response.get("prompt") or "")
        (adaptation_dir / "rendered_prompt.txt").write_text(prompt, encoding="utf-8")
        _write(adaptation_dir / "apply_template_response.json", rendered_response)
        gates.adapted_template_loaded = True
        gates.tool_name_in_prompt = "add" in prompt
        gates.tool_description_in_prompt = "Add two integers" in prompt
        gates.tool_parameters_in_prompt = all(
            token in prompt for token in ('"a"', '"b"', "integer")
        )
        if not all(
            (
                gates.tool_name_in_prompt,
                gates.tool_description_in_prompt,
                gates.tool_parameters_in_prompt,
            )
        ):
            gates.final_state = "adaptation_failed"
            return run_dir, gates
        _write(run_dir / "request.json", {"tool_round_1": payload})
        first = _post(endpoint.base_url, "/chat/completions", payload, request_timeout)
        responses["tool_round_1"] = first
        gates.rounds = 1
        first_message = _message(first)
        schemas = {
            str(tool["function"]["name"]): tool["function"]["parameters"]
            for tool in payload["tools"]
        }
        call = normalize_tool_call(
            str(first_message.get("content") or ""), tools=schemas, manifest=manifest
        )
        gates.raw_protocol_detected = call.raw_protocol
        gates.tool_name_source = manifest.tool_call.name_source
        gates.arguments_source = manifest.tool_call.arguments_source
        gates.normalization_possible = call.executable
        _write(run_dir / "normalization.json", asdict(call))
        if not gates.normalization_possible:
            gates.final_state = "adapted_prompt_only"
            return run_dir, gates
        gates.arguments_json_valid = call.executable
        if not gates.arguments_json_valid:
            gates.final_state = "adapted_call_detected"
            return run_dir, gates
        assert call.arguments is not None
        result = call.arguments["a"] + call.arguments["b"]
        gates.tool_executed = True
        assistant_protocol, observation = build_reinjection(call, result, manifest)
        followup = dict(payload)
        followup["messages"] = [*payload["messages"], assistant_protocol, observation]
        _write(
            run_dir / "reinjection.json",
            {
                "tool_result": result,
                "assistant": assistant_protocol,
                "observation": observation,
                "request": followup,
            },
        )
        try:
            final = _post(endpoint.base_url, "/chat/completions", followup, request_timeout)
        except urllib.error.HTTPError as exc:
            gates.http_errors.append(
                f"observation reinjection HTTP {exc.code}: {exc.read().decode(errors='replace')}"
            )
            gates.final_state = "adapted_execution_failed"
            return run_dir, gates
        gates.observation_reinjected = True
        responses["tool_round_2"] = final
        gates.rounds = 2
        final_message = _message(final)
        repeated = normalize_tool_call(
            str(final_message.get("content") or ""), tools=schemas, manifest=manifest
        )
        gates.repeated_call = repeated.executable
        gates.final_response_present = bool(str(final_message.get("content") or "").strip())
        gates.final_state = (
            "adapted_tools_passed"
            if gates.final_response_present and not gates.repeated_call
            else "adapted_multiround_failed"
        )
    except TimeoutError as exc:
        gates.timeout = True
        gates.http_errors.append(str(exc))
        gates.final_state = "infrastructure_failed"
    except (OSError, RuntimeError, ValueError, urllib.error.HTTPError) as exc:
        gates.http_errors.append(str(exc))
        gates.final_state = "infrastructure_failed"
    finally:
        if runtime is not None:
            gates.process_started = gates.process_started or runtime.was_started
            runtime.stop()
        gates.duration_seconds = round(time.monotonic() - started, 3)
        _write(run_dir / "response.json", responses)
        _write(run_dir / "validation.json", asdict(gates))
        _write(
            run_dir / "run_status.json", {"status": "complete", "final_state": gates.final_state}
        )
        lines = "\n".join(f"- {key}: `{value}`" for key, value in asdict(gates).items())
        (run_dir / "report.md").write_text(
            "# Adapted GLM GGUF validation\n\n"
            "- Candidate: `llama_cpp_adapted_jinja`\n"
            "- Adapter: `experimental_glm_global_tools_v1`\n\n"
            f"## Gates\n\n{lines}\n",
            encoding="utf-8",
        )
    return run_dir, gates
