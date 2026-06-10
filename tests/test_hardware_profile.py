"""Tests de presupuesto de inferencia y clasificacion doble de modelos."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from ci2lab.hardware.profile import build_cpu_profile_for_testing
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.recommend import (
    classify_memory_fit,
    classify_model_memory,
    score_recommendations,
)


def test_cpu_low_available_memory_pressure():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)

    assert profile.inference_budget_theoretical_gb == pytest.approx(7.2, abs=0.01)
    assert profile.inference_budget_available_gb == pytest.approx(1.2, abs=0.01)
    assert profile.inference_budget_gb == pytest.approx(7.2, abs=0.01)
    assert profile.memory_pressure is True


def test_cpu_high_available_no_memory_pressure():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=12.0)

    assert profile.inference_budget_theoretical_gb == pytest.approx(7.2, abs=0.01)
    assert profile.inference_budget_available_gb == pytest.approx(7.2, abs=0.01)
    assert profile.inference_budget_gb == pytest.approx(7.2, abs=0.01)
    assert profile.memory_pressure is False


def test_model_ok_if_memory_freed_when_theoretical_but_not_current():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    classification = classify_model_memory(3.0, profile)

    assert classification.required_gb == 3.0
    assert classification.theoretical_fit is True
    assert classification.current_fit is False
    assert classification.recommendation_status == "OK_IF_MEMORY_FREED"
    assert classification.fit_label == "Cabe liberando memoria"

    status, requires_cleanup, label = classify_memory_fit(3.0, profile)
    assert status == "requires_cleanup"
    assert requires_cleanup is True
    assert label == "Cabe liberando memoria"


def test_model_ok_now_when_theoretical_and_current():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=12.0)
    classification = classify_model_memory(3.0, profile)

    assert classification.theoretical_fit is True
    assert classification.current_fit is True
    assert classification.recommendation_status == "OK_NOW"
    assert classification.fit_label == "Cabe ahora"


def test_model_not_recommended_when_exceeds_theoretical():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    classification = classify_model_memory(8.0, profile)

    assert classification.theoretical_fit is False
    assert classification.current_fit is False
    assert classification.recommendation_status == "NOT_RECOMMENDED"
    assert classification.fit_label == "No recomendable"


def test_recommend_marks_llama_3b_ok_if_memory_freed_under_pressure():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    llama_3b = next(m for m in load_model_catalog() if m.id == "llama3.2-3b")

    scored = score_recommendations("", profile=profile, limit=10)
    match = next(item for item in scored if item.model.id == llama_3b.id)

    assert match.recommendation_status == "OK_IF_MEMORY_FREED"
    assert match.theoretical_fit is True
    assert match.current_fit is False
    assert match.fit_label == "Cabe liberando memoria"
    assert "cabe teoricamente" in match.reason


def test_recommend_excludes_models_above_theoretical_budget():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    mistral = next(m for m in load_model_catalog() if m.id == "mistral-7b")

    scored = score_recommendations("", profile=profile, limit=20)
    ids = {item.model.id for item in scored}

    assert mistral.id not in ids
    classification = classify_model_memory(mistral.ram_inference_gb, profile)
    assert classification.recommendation_status == "NOT_RECOMMENDED"


def test_recommend_marks_small_model_ok_now_when_ram_available_is_high():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=12.0)
    qwen = next(m for m in load_model_catalog() if m.id == "qwen2.5-coder-1.5b")

    scored = score_recommendations("", profile=profile, limit=10)
    match = next(item for item in scored if item.model.id == qwen.id)

    assert match.recommendation_status == "OK_NOW"
    assert match.theoretical_fit is True
    assert match.current_fit is True
    assert match.fit_label == "Cabe ahora"


def test_hardware_profile_dict_values_are_ascii_safe():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    for key, value in profile.to_dict().items():
        key.encode("cp1252")
        str(value).encode("cp1252")


def test_recommend_budget_messages_are_ascii_safe(monkeypatch):
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    buf = StringIO()
    monkeypatch.setattr("ci2lab.cli.console", Console(file=buf, width=160))

    from ci2lab.cli import _print_memory_budget_context

    _print_memory_budget_context(profile)

    for line in buf.getvalue().splitlines():
        line.encode("cp1252")

    output = buf.getvalue()
    assert "teoricamente" in output
    assert "presion de memoria" in output


def test_recommend_fit_labels_are_ascii_safe():
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=2.0)
    scored = score_recommendations("", profile=profile, limit=5)
    for item in scored:
        item.fit_label.encode("cp1252")
        item.reason.encode("cp1252")
        item.recommendation_status.encode("cp1252")
