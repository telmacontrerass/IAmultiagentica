from ci2lab.hardware.profile import build_cpu_profile_for_testing
from ci2lab.runtime.ollama import is_catalog_model_installed
from ci2lab.router.recommend import (
    _score_for_category,
    build_display_recommendations,
    recommend_download_plan,
    score_recommendations,
)


def test_is_catalog_model_installed_matches_exact_and_variant_tags():
    installed = {"qwen2.5:7b", "llama3.2:3b-instruct-q4_K_M"}
    assert is_catalog_model_installed("qwen2.5:7b", installed)
    assert is_catalog_model_installed("llama3.2:3b", installed)
    assert not is_catalog_model_installed("gemma2:2b", installed)


def test_build_display_recommendations_shows_installed_and_download_suggestions():
    profile = build_cpu_profile_for_testing(ram_total_gb=32.0, ram_available_gb=16.0)
    pool = score_recommendations("", profile=profile, limit=20)
    installed_tag = pool[0].model.ollama_tag
    installed_names = {installed_tag}

    display = build_display_recommendations(pool, installed_names, limit=4)

    assert len(display) == 4
    assert display[0].installed is True
    assert display[0].item.model.ollama_tag == installed_tag
    assert any(not entry.installed for entry in display[1:])


def test_build_display_recommendations_without_installed_matches_legacy_order():
    profile = build_cpu_profile_for_testing(ram_total_gb=32.0, ram_available_gb=16.0)
    pool = score_recommendations("", profile=profile, limit=5)
    display = build_display_recommendations(pool, set(), limit=5)

    assert [entry.item.model.id for entry in display] == [item.model.id for item in pool]


def test_download_plan_suggests_next_model_when_top_is_installed():
    profile = build_cpu_profile_for_testing(ram_total_gb=32.0, ram_available_gb=16.0)
    scored = _score_for_category("reasoning", profile=profile, limit=20)
    top = scored[0]
    installed_names = {top.model.ollama_tag}

    plan = recommend_download_plan(
        profile=profile,
        installed_names=installed_names,
        use_cases=("reasoning",),
    )

    installed_rows = [item for item in plan if item.installed]
    download_rows = [item for item in plan if not item.installed]

    assert len(installed_rows) == 1
    assert installed_rows[0].recommendation.model.id == top.model.id
    assert len(download_rows) == 1
    assert download_rows[0].recommendation.model.id != top.model.id
    assert not is_catalog_model_installed(
        download_rows[0].recommendation.model.ollama_tag,
        installed_names,
    )


def test_download_plan_keeps_separate_rows_per_use_case():
    profile = build_cpu_profile_for_testing(ram_total_gb=32.0, ram_available_gb=16.0)
    plan = recommend_download_plan(profile=profile, installed_names=set())

    assert all(len(item.use_cases) == 1 for item in plan)
    download_rows = [item for item in plan if not item.installed]
    assert len(download_rows) == 4
    assert len({item.use_cases[0] for item in download_rows}) == 4
