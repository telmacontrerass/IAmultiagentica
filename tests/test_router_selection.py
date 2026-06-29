from unittest.mock import patch

from ci2lab.contracts import HardwareProfile
from ci2lab.router.catalog import find_model_by_tag
from ci2lab.router.selection import build_model_selection


def _profile() -> HardwareProfile:
    return HardwareProfile(
        ram_total_gb=32.0,
        ram_available_gb=16.0,
        vram_total_gb=8.0,
        vram_available_gb=7.0,
        gpu_name="Test GPU",
        gpu_vendor="nvidia",
        cpu_cores=8,
        os="windows",
        inference_mode="gpu",
        inference_budget_gb=5.5,
        inference_budget_theoretical_gb=6.0,
        inference_budget_available_gb=5.5,
        memory_pressure=False,
    )


def test_find_model_by_tag_matches_id_and_ollama_tag():
    by_id = find_model_by_tag("qwen2.5-coder-7b")
    by_tag = find_model_by_tag("qwen2.5-coder:7b")

    assert by_id is not None
    assert by_tag is not None
    assert by_id.id == by_tag.id == "qwen2.5-coder-7b"


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_build_model_selection_uses_catalog_tool_mode(_mock_scan):
    selection = build_model_selection("qwen2.5-coder:7b")

    assert selection.tool_mode == "native"
    assert selection.model_id == "qwen2.5-coder-7b"
    assert selection.supports_tools is True


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_build_model_selection_unknown_model_defaults_fenced(_mock_scan):
    selection = build_model_selection("some-unknown:7b")

    assert selection.tool_mode == "fenced"
    assert selection.warnings


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_build_model_selection_explicit_override(_mock_scan):
    selection = build_model_selection(
        "qwen2.5-coder:7b",
        tool_mode_override="fenced",
    )

    assert selection.tool_mode == "fenced"


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_build_model_selection_uses_catalog_context_length(_mock_scan, monkeypatch):
    monkeypatch.delenv("CI2LAB_NUM_CTX", raising=False)
    selection = build_model_selection("mixtral:8x22b")

    assert selection.context_length == 65536


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_num_ctx_env_override_caps_context_length(_mock_scan, monkeypatch):
    # The override drives both the Ollama num_ctx and the harness compaction
    # math, so they stay consistent.
    monkeypatch.setenv("CI2LAB_NUM_CTX", "16384")
    selection = build_model_selection("mixtral:8x22b")

    assert selection.context_length == 16384


def _roomy_profile() -> HardwareProfile:
    """A machine with ample VRAM, enough to hold any catalog window."""
    return HardwareProfile(
        ram_total_gb=256.0,
        ram_available_gb=200.0,
        vram_total_gb=80.0,
        vram_available_gb=78.0,
        gpu_name="Big GPU",
        gpu_vendor="nvidia",
        cpu_cores=32,
        os="linux",
        inference_mode="gpu",
        inference_budget_gb=76.0,
        inference_budget_theoretical_gb=78.0,
        inference_budget_available_gb=76.0,
        memory_pressure=False,
    )


def test_context_defaults_to_native_max_when_memory_ample(monkeypatch):
    monkeypatch.delenv("CI2LAB_NUM_CTX", raising=False)
    selection = build_model_selection("llama3.2:3b", profile=_roomy_profile())
    # Native max from the catalog flows through untouched on a roomy machine.
    assert selection.context_length == 131072


def test_context_capped_to_hardware_when_memory_tight(monkeypatch):
    monkeypatch.delenv("CI2LAB_NUM_CTX", raising=False)
    # 5.5 GB budget cannot hold the KV cache for the full 131072 window.
    selection = build_model_selection("llama3.2:3b", profile=_profile())
    assert 2048 <= selection.context_length < 131072
    assert selection.context_length % 1024 == 0


def test_context_keeps_native_when_model_exceeds_budget(monkeypatch):
    monkeypatch.delenv("CI2LAB_NUM_CTX", raising=False)
    # Weights alone (78.6 GB) exceed the 5.5 GB budget, so window capping is
    # moot — the native window is preserved rather than reported as tiny.
    selection = build_model_selection("mixtral:8x22b", profile=_profile())
    assert selection.context_length == 65536


def test_num_ctx_override_beats_hardware_cap(monkeypatch):
    monkeypatch.setenv("CI2LAB_NUM_CTX", "100000")
    selection = build_model_selection("llama3.2:3b", profile=_profile())
    # The explicit operator override wins over the hardware-aware cap.
    assert selection.context_length == 100000


@patch("ci2lab.router.selection.scan_hardware", return_value=_profile())
def test_prepare_session_does_not_auto_pick_router_model(_mock_scan):
    from ci2lab.pipeline import prepare_session

    _, selection = prepare_session(
        "programar en python",
        force_model="qwen2.5-coder:7b",
        pull=False,
    )

    assert selection.ollama_tag == "qwen2.5-coder:7b"
    assert selection.tool_mode == "native"
