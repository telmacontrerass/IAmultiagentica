from __future__ import annotations

import json
import struct
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ci2lab.router.gguf_import.ad_comparison import (
    Attempt,
    AttemptTimedOut,
    _post_with_evidence,
    execute,
    prepare_workspace,
)
from ci2lab.router.gguf_import.adaptation import (
    adapt_glm_global_tools,
    sha256_text,
    write_text_exact,
)
from ci2lab.router.gguf_import.adapter_manifest import get_adapter, load_adapter_catalog
from ci2lab.router.gguf_import.benchmark import ScenarioResult, summarize_results
from ci2lab.router.gguf_import.candidates import BUILTIN_CANDIDATES, RuntimeTemplateContract
from ci2lab.router.gguf_import.inspector import analyze_template, inspect_gguf
from ci2lab.router.gguf_import.normalizer import build_reinjection, normalize_tool_call
from ci2lab.router.gguf_import.safe_tools import AdaptedRoundGuard, execute_validation_tool
from ci2lab.router.gguf_import.source import GGUFSourceResolver
from ci2lab.router.gguf_import.transforms import apply_template_transform
from ci2lab.router.gguf_import.validation import ValidationGates
from ci2lab.runtime.llama_cpp import LlamaCppRuntime, choose_free_port, resolve_llama_server


def _string(value: str) -> bytes:
    encoded = value.encode()
    return struct.pack("<Q", len(encoded)) + encoded


def _gguf(path: Path, metadata: dict[str, object]) -> None:
    body = b"GGUF" + struct.pack("<IQQ", 3, 0, len(metadata))
    for key, value in metadata.items():
        body += _string(key)
        if isinstance(value, int):
            body += struct.pack("<I", 4) + struct.pack("<I", value)
        else:
            body += struct.pack("<I", 8) + _string(str(value))
    path.write_bytes(body)


def test_local_source_hash_and_metadata(tmp_path):
    model = tmp_path / "model.gguf"
    _gguf(model, {"general.architecture": "glm4", "glm4.context_length": 16384})
    source = GGUFSourceResolver().resolve_local(model)
    assert source.size_bytes == model.stat().st_size
    assert len(source.sha256) == 64
    inspection = inspect_gguf(model)
    assert inspection.architecture == "glm4"
    assert inspection.context_length == 16384


def test_jinja_analysis_exposes_glm_contract_mismatch():
    template = "{% for item in messages %}{% if item['tools'] is defined %}{{ item['tools'] }}{% endif %}{% if item.role == 'observation' %}{{ item.content }}{% endif %}{% endfor %}{{ assistant.metadata }}"
    analysis = analyze_template(template)
    assert analysis.tool_schema_sources == ("messages[*].tools",)
    assert analysis.tool_call_name_sources == ("assistant.metadata",)
    assert analysis.tool_result_roles == ("observation",)
    assert RuntimeTemplateContract().tools_variable == "tools"


def test_candidate_serialization():
    payload = BUILTIN_CANDIDATES["llama_cpp_original_jinja"].to_dict()
    assert payload["runtime"] == "llama.cpp"
    assert payload["template_origin"] == "gguf_original"


def test_validation_has_explicit_infrastructure_state_and_startup_timing():
    gates = ValidationGates()
    gates.final_state = "infrastructure_failed"
    assert gates.final_state != "incompatible_tools"
    assert gates.startup_duration_seconds == 0


def test_glm_adapter_is_minimal_and_preserves_special_protocol():
    original = (
        "[gMASK]<sop>{% for item in messages %}{% if item['tools'] is defined %}"
        "{{ item['tools'] }}{% endif %}<|{{ item['role'] }}|>{{ item['metadata'] }}"
        "{{ item['content'] }}{% endfor %}python simple_browser cogview observation"
    )
    adapted, manifest, diff = adapt_glm_global_tools(original)
    assert adapted.endswith(original.removeprefix("[gMASK]<sop>"))
    assert "tools is defined and tools" in adapted
    assert all(
        token in adapted
        for token in (
            "[gMASK]<sop>",
            "metadata",
            "python",
            "simple_browser",
            "cogview",
            "observation",
        )
    )
    assert manifest.original_template_sha256 == sha256_text(original)
    assert manifest.adapted_template_sha256 == sha256_text(adapted)
    assert manifest.adapter_id == "experimental_glm_global_tools_v1"
    assert diff.startswith("--- original_template.jinja")


def test_adapted_template_file_hash_matches_manifest_on_windows(tmp_path):
    original = "[gMASK]<sop>{% for item in messages %}{{ item['tools'] }}\n{% endfor %}"
    adapted, manifest, _diff = adapt_glm_global_tools(original)
    path = tmp_path / "adapted.jinja"
    write_text_exact(path, adapted)
    assert path.read_bytes() == adapted.encode("utf-8")
    assert sha256_text(path.read_text(encoding="utf-8")) == manifest.adapted_template_sha256


def test_allowlisted_transform_checks_preconditions_diff_and_hash():
    original = "[gMASK]<sop>{% for item in messages %}{{ item['tools'] }}{% endfor %}\n"
    legacy_adapted, _legacy_manifest, _diff = adapt_glm_global_tools(original)
    manifest = get_adapter("experimental_glm_global_tools_v1")
    manifest = replace(
        manifest,
        match=replace(manifest.match, original_template_sha256=sha256_text(original)),
        transform=replace(
            manifest.transform,
            expected_adapted_template_sha256=sha256_text(legacy_adapted),
        ),
    )
    result = apply_template_transform(original, manifest)
    assert result.adapted == legacy_adapted
    assert result.diff.startswith("--- original_template.jinja")
    with pytest.raises(ValueError, match="hash mismatch"):
        apply_template_transform(original + "changed", manifest)


def _tool_schemas():
    return {
        "add": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        "echo": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "configure": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["fast", "safe"]},
                "note": {"type": "string"},
            },
            "required": ["enabled", "mode"],
        },
    }


def test_declarative_normalizer_preserves_premature_final_as_diagnostic():
    call = normalize_tool_call(
        'add\n{"a": 2, "b": 3}\nThe result of 2+3 is 5.',
        tools=_tool_schemas(),
        manifest=get_adapter("experimental_glm_global_tools_v1"),
    )
    assert call.executable and call.arguments == {"a": 2, "b": 3}
    assert call.trailing_text == "The result of 2+3 is 5."
    assistant, observation = build_reinjection(
        call, 5, get_adapter("experimental_glm_global_tools_v1")
    )
    assert assistant == {"role": "assistant", "metadata": "add", "content": '{"a":2,"b":3}'}
    assert observation == {"role": "observation", "metadata": "", "content": "5"}


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("missing\n{}", "unknown_tool"),
        ("add\nnot-json", "invalid_json"),
        ('add\n{"a":2}', "schema_validation"),
        ('add\n{"a":"2","b":3}', "schema_validation"),
        ('add\n{"a":2,"b":3}\n{"a":4,"b":5}', "multiple_json"),
        ('prose before add\nadd\n{"a":2,"b":3}', "unknown_tool"),
        ('```json\n{"a":2}\n```', "unknown_tool"),
    ],
)
def test_declarative_normalizer_rejects_unsafe_or_ambiguous_calls(raw, reason):
    call = normalize_tool_call(
        raw, tools=_tool_schemas(), manifest=get_adapter("experimental_glm_global_tools_v1")
    )
    assert not call.executable
    assert call.rejection_reason == reason


def test_declarative_normalizer_supports_selection_optional_boolean_and_enum():
    manifest = get_adapter("experimental_glm_global_tools_v1")
    echo = normalize_tool_call('echo\n{"text":"hi"}', tools=_tool_schemas(), manifest=manifest)
    configured = normalize_tool_call(
        'configure\n{"enabled":true,"mode":"safe"}',
        tools=_tool_schemas(),
        manifest=manifest,
    )
    bad_enum = normalize_tool_call(
        'configure\n{"enabled":true,"mode":"unknown"}',
        tools=_tool_schemas(),
        manifest=manifest,
    )
    assert echo.name == "echo" and echo.executable
    assert configured.executable
    assert not bad_enum.executable


def test_catalog_requires_strict_match_and_can_be_disabled(tmp_path):
    adapter = get_adapter("experimental_glm_global_tools_v1")
    assert adapter.adapted_tool_mode == "adapted_native"
    assert adapter.status == "experimental"
    assert adapter.runtime_version_compatible("version: 9994 (14d3ba45f)")
    assert not adapter.runtime_version_compatible("version: 9000")
    assert adapter.matches(
        architecture="chatglm",
        template_sha256=adapter.match.original_template_sha256,
        runtime="llama.cpp",
    )
    assert not adapter.matches(
        architecture="chatglm", template_sha256="changed", runtime="llama.cpp"
    )
    payload = {
        "schema_version": 1,
        "adapters": [
            {
                **json.loads(Path("ci2lab/catalog/experimental_gguf_adapters.json").read_text())[
                    "adapters"
                ][0],
                "enabled": False,
            }
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload))
    assert not load_adapter_catalog(path)[0].matches(
        architecture="chatglm",
        template_sha256=adapter.match.original_template_sha256,
        runtime="llama.cpp",
    )


def test_benchmark_summary_is_objective_and_does_not_invent_fenced_data():
    results = [
        ScenarioResult("ok", True, True, True, True, True, True, True, False, 2, 10.0, "passed"),
        ScenarioResult(
            "repeat", True, True, True, True, True, True, False, True, 3, 20.0, "failed"
        ),
    ]
    summary = summarize_results(results)
    assert summary["valid_call_rate"] == 1
    assert summary["final_rate"] == 0.5
    assert summary["repeat_rate"] == 0.5
    assert summary["mean_rounds"] == 2.5
    assert summarize_results([])["valid_call_rate"] is None


def test_safe_validation_tools_cover_success_error_and_observation_error():
    assert execute_validation_tool("add", {"a": 2, "b": 3}).value == 5
    assert execute_validation_tool("echo", {"text": "hello"}).value == "hello"
    assert execute_validation_tool("annotate", {"text": "hello"}).ok
    assert execute_validation_tool("configure", {"enabled": True, "mode": "safe"}).ok
    error = execute_validation_tool("fail_safely", {})
    assert not error.ok and error.error == "intentional_validation_error"
    assert not execute_validation_tool("unknown", {}).ok


def test_opaque_and_fixture_tools_are_runtime_only_and_confined(tmp_path):
    opaque = execute_validation_tool("opaque_value", {"seed": "x"})
    assert opaque.ok and str(opaque.value).startswith("OBS_")
    fixture = tmp_path / "fixture_secret.txt"
    fixture.write_text("FILE_VALUE_TEST")
    assert (
        execute_validation_tool(
            "read_fixture", {"path": "fixture_secret.txt"}, fixture_root=tmp_path
        ).value
        == "FILE_VALUE_TEST"
    )
    assert not execute_validation_tool(
        "read_fixture", {"path": "../outside.txt"}, fixture_root=tmp_path
    ).ok
    assert not execute_validation_tool(
        "read_fixture", {"path": str(fixture.resolve())}, fixture_root=tmp_path
    ).ok


def test_multiround_guard_allows_sequence_rejects_repeat_and_limits_rounds():
    manifest = get_adapter("experimental_glm_global_tools_v1")
    first = normalize_tool_call('echo\n{"text":"2+3"}', tools=_tool_schemas(), manifest=manifest)
    second = normalize_tool_call('add\n{"a":2,"b":3}', tools=_tool_schemas(), manifest=manifest)
    guard = AdaptedRoundGuard(max_rounds=2)
    assert guard.accept(first) == (True, None)
    assert guard.accept(first) == (False, "repeated_call")
    assert guard.accept(second) == (True, None)
    assert guard.accept(
        normalize_tool_call('echo\n{"text":"done"}', tools=_tool_schemas(), manifest=manifest)
    ) == (False, "round_limit")


def test_choose_free_port_is_bindable():
    assert 0 < choose_free_port() < 65536


def test_resolve_binary_priority(tmp_path, monkeypatch):
    explicit = tmp_path / "llama-server.exe"
    explicit.write_bytes(b"")
    env = tmp_path / "other.exe"
    env.write_bytes(b"")
    monkeypatch.setenv("CI2LAB_LLAMA_SERVER", str(env))
    assert resolve_llama_server(explicit) == explicit.resolve()


def test_runtime_builds_argument_list_and_stops_process(tmp_path):
    binary = tmp_path / "llama-server.exe"
    binary.write_bytes(b"")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    runtime = LlamaCppRuntime(model, binary=binary, context_length=42, log_dir=tmp_path / "logs")
    command = runtime.build_command()
    assert command[0] == str(binary.resolve())
    assert command[command.index("--model") + 1] == str(model.resolve())
    assert command[command.index("--ctx-size") + 1] == "42"
    process = MagicMock()
    process.poll.return_value = None
    runtime.process = process
    runtime.stop()
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=10)


def test_runtime_uses_official_external_template_flag(tmp_path):
    binary = tmp_path / "llama-server.exe"
    binary.write_bytes(b"")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    template = tmp_path / "adapted.jinja"
    template.write_text("template")
    runtime = LlamaCppRuntime(
        model, binary=binary, log_dir=tmp_path / "logs", template_path=template
    )
    command = runtime.build_command()
    assert command[-3:] == ["--jinja", "--chat-template-file", str(template.resolve())]


def test_start_timeout_cleans_up(tmp_path, monkeypatch):
    binary = tmp_path / "llama-server.exe"
    binary.write_bytes(b"")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    runtime = LlamaCppRuntime(model, binary=binary, startup_timeout=0, log_dir=tmp_path / "logs")
    process = MagicMock()
    process.poll.return_value = None
    monkeypatch.setattr("ci2lab.runtime.llama_cpp.subprocess.Popen", lambda *_a, **_k: process)
    with pytest.raises(TimeoutError):
        runtime.start()
    process.terminate.assert_called_once()


def test_health_check_simulated(tmp_path):
    binary = tmp_path / "llama-server.exe"
    binary.write_bytes(b"")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    runtime = LlamaCppRuntime(model, binary=binary, log_dir=tmp_path / "logs")
    with patch.object(runtime, "_request", side_effect=[(200, {}), (200, {"data": [{"id": "m"}]})]):
        assert runtime.health_check().healthy


def test_inspect_command_does_not_write_registry(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    _gguf(model, {"general.architecture": "glm4"})
    registry = tmp_path / "registry.json"
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))
    from ci2lab.cli import main

    assert main(["models", "inspect-gguf", "--model-path", str(model)]) == 0
    assert not registry.exists()


def test_adapter_catalog_cli_does_not_promote_to_registry(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    monkeypatch.setenv("CI2LAB_IMPORTED_MODELS_PATH", str(registry))
    from ci2lab.cli import main

    assert main(["models", "adapters", "list"]) == 0
    assert main(["models", "adapters", "inspect", "experimental_glm_global_tools_v1"]) == 0
    assert not registry.exists()


def test_ad_comparison_uses_confined_common_executor(tmp_path: Path) -> None:
    workspace = tmp_path / "benchmark_workspace"
    prepare_workspace(workspace)

    ok, value, blocked = execute("read_file", {"path": "secret_alpha.txt"}, workspace)
    assert (ok, value, blocked) == (True, "ALPHA_VALUE_7F3C91", False)

    ok, _value, blocked = execute(
        "write_file", {"path": "../outside.txt", "content": "NO"}, workspace
    )
    assert not ok
    assert blocked
    assert not (tmp_path / "outside.txt").exists()


def test_ad_comparison_typed_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "benchmark_workspace"
    prepare_workspace(workspace)
    assert execute("add", {"a": 17, "b": 25}, workspace) == (True, "42", False)
    ok, record, blocked = execute(
        "format_record",
        {
            "name": "adapter-test",
            "enabled": True,
            "tags": ["gguf", "glm4"],
            "mode": "experimental",
        },
        workspace,
    )
    assert ok and not blocked
    assert json.loads(record)["enabled"] is True


def test_attempt_evidence_defaults_do_not_claim_validation_or_execution() -> None:
    attempt = Attempt("adapted_native", "no-tools", [])
    assert attempt.tool_call_candidates_detected == 0
    assert attempt.tool_calls_attempted == 0
    assert attempt.tool_calls_accepted == 0
    assert attempt.tool_calls_rejected == 0
    assert attempt.executed_tool_count == 0
    assert not attempt.execution_attempted
    assert attempt.all_attempted_executions_succeeded is None
    assert not attempt.arguments_validation_attempted
    assert attempt.all_arguments_valid is None
    assert not attempt.observation_message_created
    assert not attempt.observation_sent_to_model
    assert not attempt.post_observation_response_received
    assert attempt.parser_rejection_reason is None
    assert attempt.timeout_phase is None
    assert attempt.timeout_round is None


def test_timeout_preserves_round_phase_and_prior_observation(monkeypatch) -> None:
    attempt = Attempt("adapted_native", "timeout", [])
    attempt.observation_sent_to_model = True

    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("ci2lab.router.gguf_import.ad_comparison._post", timeout)
    with pytest.raises(AttemptTimedOut) as caught:
        _post_with_evidence(
            "http://unused",
            {},
            1,
            attempt=attempt,
            round_no=2,
            started=0,
        )
    recorded = caught.value.attempt
    assert recorded.observation_sent_to_model
    assert recorded.timeout_phase == "model_request"
    assert recorded.timeout_round == 2
    assert recorded.elapsed_seconds is not None
