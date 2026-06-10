from ci2lab.pipeline import prepare_session
from ci2lab.router.catalog import load_model_catalog


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
