import json
from dataclasses import replace
from subprocess import CompletedProcess

from ci2lab.cli.parser import build_parser
from ci2lab.router.gguf_import.capabilities import ToolCallingCapability
from ci2lab.router.gguf_import.ollama_identity import (
    OllamaModelSnapshot,
    decide_identity,
    expected_identity,
    safe_rollback_created_model,
    snapshot_ollama_model,
)
from ci2lab.router.gguf_import.smoke_runner import run_smoke_suite
from ci2lab.router.imported_models import build_imported_profile, render_ollama_modelfile


def _profile():
    profile = build_imported_profile(
        model_id="smoke",
        ollama_tag="ci2lab/smoke:latest",
        repo="repo/model",
        filename="model-Q4_K_M.gguf",
        local_path="model.gguf",
        family="glm4",
        template_id="glm4-chat",
        context_length=8192,
    )
    return replace(
        profile,
        source={
            **profile.source,
            "sha256": "abc",
            "architecture": "glm4",
            "quantization": "Q4_K_M",
            "template_sha256": "template",
        },
        capabilities=replace(
            profile.capabilities,
            tool_calling=ToolCallingCapability(
                protocol="native",
                parser="openai_tool_calls",
                evidence_level="configured",
            ),
        ),
    )


class FakeNativeTransport:
    def __init__(self):
        self.closed = False
        self.first_messages = 0

    def close(self):
        self.closed = True

    def complete(self, payload, _timeout):
        messages = payload["messages"]
        prompt = messages[0]["content"]
        if len(messages) == 1:
            self.first_messages += 1
        tool_messages = [item for item in messages if item["role"] == "tool"]
        if not tool_messages:
            if "únicamente con la palabra OK" in prompt:
                return _final("OK")
            if "no ejecutes" in prompt:
                return _final("read_file necesita path")
            if "numbers.csv" in prompt:
                return _call("read_file", {"path": "numbers.csv"})
            if "copia exactamente" in prompt:
                return _call("read_file", {"path": "secret_alpha.txt"})
            if "37 y 58" in prompt:
                return _call("add", {"a": 37, "b": 58})
            if "opaque_value" in prompt:
                return _call("opaque_value", {"seed": "gguf-import-smoke"})
            if "output/smoke.txt" in prompt:
                return _call("write_file", {"path": "output/smoke.txt", "content": "GGUF_SMOKE_OK"})
            if "format_record" in prompt:
                return _call(
                    "format_record",
                    {
                        "name": "gguf-import-smoke",
                        "enabled": True,
                        "tags": ["gguf", "smoke"],
                        "mode": "experimental",
                    },
                )
            if "always_fail" in prompt:
                return _call("always_fail", {"message": "gguf-import-smoke"})
            if "outside.txt" in prompt:
                return _call("read_file", {"path": "../outside.txt"})
            if "untrusted.txt" in prompt:
                return _call("read_file", {"path": "notes/untrusted.txt"})
        if "numbers.csv" in prompt and len(tool_messages) == 1:
            return _call("add", {"a": 17, "b": 25})
        if "copia exactamente" in prompt and len(tool_messages) == 1:
            return _call("write_file", {"path": "output/copy.txt", "content": "ALPHA_VALUE_7F3C91"})
        if "opaque_value" in prompt:
            return _final(tool_messages[-1]["content"])
        if "37 y 58" in prompt:
            return _final("95")
        if "numbers.csv" in prompt:
            return _final("42")
        if "always_fail" in prompt:
            return _final("Reconozco el error controlado")
        return _final("hecho")


def _call(name, arguments):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{name}",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _final(content):
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def test_official_smoke_reuses_transport_fresh_conversations_and_promotes(tmp_path):
    transport = FakeNativeTransport()
    registry = tmp_path / "registry.json"
    artifact, promoted = run_smoke_suite(
        _profile(),
        transport,
        evidence_dir=tmp_path / "evidence",
        registry_path=registry,
    )
    assert transport.closed
    assert transport.first_messages == 11
    assert artifact["attempt_count"] == 11
    assert artifact["capabilities"]["tool_calling_verified"]
    assert artifact["capabilities"]["workspace_confinement_verified"]
    assert artifact["capabilities"]["untrusted_content_resistance_verified"]
    assert promoted.capabilities.tool_calling.verified
    assert json.loads((tmp_path / "evidence/smoke_results.json").read_text())["schema_version"] == 1
    assert registry.is_file()


def test_smoke_no_promote_and_transport_closes_on_exception(tmp_path):
    transport = FakeNativeTransport()
    registry = tmp_path / "registry.json"
    _artifact, promoted = run_smoke_suite(
        _profile(),
        transport,
        evidence_dir=tmp_path / "no-promote",
        registry_path=registry,
        promote=False,
    )
    assert not promoted.capabilities.tool_calling.verified
    assert not registry.exists()

    class Broken(FakeNativeTransport):
        def complete(self, payload, timeout):
            raise RuntimeError("broken")

    broken = Broken()
    artifact, _profile_after_error = run_smoke_suite(
        _profile(), broken, evidence_dir=tmp_path / "broken", promote=False
    )
    assert broken.closed
    assert not artifact["capabilities"]["inference_verified"]


def test_identity_equivalence_conflicts_and_latest():
    profile = _profile()
    identity = expected_identity(profile, render_ollama_modelfile(profile))
    snapshot = OllamaModelSnapshot(
        "ci2lab/smoke",
        "ci2lab/smoke:latest",
        True,
        digest="digest",
    )
    equivalent = decide_identity(identity, snapshot, identity.to_dict())
    assert equivalent.state == "ALREADY_IMPORTED_EQUIVALENT"
    different = identity.to_dict() | {"gguf_sha256": "different"}
    assert decide_identity(identity, snapshot, different).state == "IMPORT_CONFLICT"
    q4 = replace(identity, tag="ci2lab/smoke:q4")
    assert decide_identity(q4, snapshot, q4.to_dict()).state == "IMPORT_CONFLICT"
    assert decide_identity(identity, replace(snapshot, exists=False), identity.to_dict()).state == (
        "PROFILE_MODEL_INCONSISTENT"
    )
    assert decide_identity(identity, snapshot, None).state == "EXTERNAL_MODEL_UNTRACKED"


def test_snapshot_and_safe_rollback_require_stable_attributed_digest(monkeypatch):
    payload = {
        "name": "model:latest",
        "digest": "d1",
        "modelfile": "PARAMETER num_ctx 8192",
        "details": {"family": "qwen3", "quantization_level": "Q4_K_M"},
        "model_info": {"qwen3.context_length": 8192},
    }
    calls = []

    def run(args, **_kwargs):
        calls.append(args)
        if args[1] == "show":
            return CompletedProcess(args, 0, json.dumps(payload), "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("ci2lab.router.gguf_import.ollama_identity.subprocess.run", run)
    snapshot = snapshot_ollama_model("model")
    assert snapshot.exists and snapshot.context_length == 8192
    before = replace(snapshot, exists=False, digest=None)
    assert safe_rollback_created_model("model", before=before, after_creation=snapshot)
    assert calls[-1] == ["ollama", "rm", "model"]
    assert not safe_rollback_created_model("model", before=snapshot, after_creation=snapshot)


def test_cli_exposes_official_smoke_command():
    args = build_parser().parse_args(
        ["models", "gguf-import-smoke", "--model", "smoke", "--no-promote"]
    )
    assert args.models_command == "gguf-import-smoke"
    assert args.no_promote
