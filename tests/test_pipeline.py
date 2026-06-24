from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.security_profiles import SecurityConfig
from ci2lab.pipeline import prepare_session, resolve_tool_output_budget
from ci2lab.router.catalog import load_model_catalog


def _selection(context_length: int) -> ModelSelection:
    return ModelSelection(
        model_id="m",
        ollama_tag="m:latest",
        display_name="M",
        context_length=context_length,
    )


def test_tool_output_budget_scales_to_context_window():
    # A 64k-token window should let an ordinary document (a few thousand chars)
    # pass through inline instead of being offloaded to disk as head+tail.
    budget = resolve_tool_output_budget(_selection(65536), SecurityConfig())
    assert budget == 65536 * 4 * 0.5
    assert budget > 11757  # the failing exam PDF now fits whole


def test_tool_output_budget_respects_explicit_override():
    sec = SecurityConfig(max_tool_output_chars=5000)
    assert resolve_tool_output_budget(_selection(65536), sec) == 5000


def test_tool_output_budget_has_floor_for_tiny_context():
    assert resolve_tool_output_budget(_selection(1024), SecurityConfig()) == 8000


def test_tool_output_budget_is_capped_for_huge_context():
    assert resolve_tool_output_budget(_selection(1_000_000), SecurityConfig()) == 200_000


def test_prepare_session_fallback_resolves_catalog_id_to_ollama_tag():
    _, selection = prepare_session(
        "",
        force_model="qwen2.5-coder-1.5b",
        pull=False,
    )

    assert selection.model_id == "qwen2.5-coder-1.5b"
    assert selection.ollama_tag == "qwen2.5-coder:1.5b"
    assert selection.display_name == "Qwen2.5 Coder 1.5B"


def test_prepare_session_fallback_accepts_ollama_tag():
    _, selection = prepare_session(
        "",
        force_model="qwen2.5-coder:1.5b",
        pull=False,
    )

    assert selection.model_id == "qwen2.5-coder-1.5b"
    assert selection.ollama_tag == "qwen2.5-coder:1.5b"


def test_prepare_session_fallback_resolves_all_catalog_ids_and_tags():
    for model in load_model_catalog():
        _, by_id = prepare_session("", force_model=model.id, pull=False)
        _, by_tag = prepare_session("", force_model=model.ollama_tag, pull=False)

        assert by_id.model_id == model.id
        assert by_id.ollama_tag == model.ollama_tag
        assert by_tag.model_id == model.id
        assert by_tag.ollama_tag == model.ollama_tag
