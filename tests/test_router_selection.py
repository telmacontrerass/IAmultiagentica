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
def test_prepare_session_does_not_auto_pick_router_model(_mock_scan):
    from ci2lab.pipeline import prepare_session

    _, selection = prepare_session(
        "programar en python",
        force_model="qwen2.5-coder:7b",
        pull=False,
    )

    assert selection.ollama_tag == "qwen2.5-coder:7b"
    assert selection.tool_mode == "native"
