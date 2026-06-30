"""Tests for the login-less researcher-profile store."""

from pathlib import Path

from ci2lab.ui import researchers


def _use_temp_registry(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "researchers.json"
    monkeypatch.setattr(researchers, "researchers_path", lambda: path)
    return path


def test_create_and_list_researcher(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    result = researchers.create_researcher(
        {
            "name": "Dr Ada",
            "instructions": "Review rigorously; check the statistics.",
            "rubrics": [{"name": "methods.md", "content": "## Methods\n- reproducible?"}],
        }
    )
    assert result["ok"] is True
    researcher = result["researcher"]
    assert researcher["id"].startswith("rsr_")
    assert researcher["instructions"] == "Review rigorously; check the statistics."
    assert [r["name"] for r in researcher["rubrics"]] == ["methods.md"]
    # The profile is now just name + documents; structured fields are gone.
    assert "fields" not in researcher
    assert "lens_preferences" not in researcher

    listing = researchers.list_researchers()
    assert [r["id"] for r in listing] == [researcher["id"]]


def test_create_requires_name(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    result = researchers.create_researcher({"name": "   "})
    assert result["ok"] is False


def test_update_and_delete_researcher(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    created = researchers.create_researcher({"name": "Reviewer One"})["researcher"]

    updated = researchers.update_researcher(
        created["id"], {"name": "Reviewer One", "instructions": "Be fair but firm."}
    )
    assert updated["ok"] is True
    assert updated["researcher"]["instructions"] == "Be fair but firm."
    assert updated["researcher"]["created_at"] == created["created_at"]

    deleted = researchers.delete_researcher(created["id"])
    assert deleted["ok"] is True
    assert researchers.get_researcher(created["id"]) is None
    assert researchers.list_researchers() == []


def test_researcher_prompt_appends_profile_block(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    created = researchers.create_researcher(
        {"name": "Dr Ada", "instructions": "Focus on software engineering rigor."}
    )["researcher"]

    prompt = researchers.researcher_prompt(created["id"], "Review this paper.")
    assert "Review this paper." in prompt
    assert "reviewer_profile" in prompt
    assert "software engineering rigor" in prompt
    # The profile must never be a license to invent.
    assert "verbatim quote and anchor" in prompt


def test_researcher_prompt_is_noop_without_profile(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    assert researchers.researcher_prompt("", "hello") == "hello"
    assert researchers.researcher_prompt("rsr_missing", "hello") == "hello"


def test_instructions_and_rubrics_persist_and_ground_the_prompt(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    created = researchers.create_researcher(
        {
            "name": "Dr Ada",
            "instructions": "Be rigorous.\r\nCheck the statistics.",
            "rubrics": [
                {"name": "methods.md", "content": "## Methods\n- reproducible?"},
                {"name": "", "content": ""},
                "not a dict",
            ],
        }
    )["researcher"]

    assert created["instructions"] == "Be rigorous.\nCheck the statistics."
    assert [r["name"] for r in created["rubrics"]] == ["methods.md"]

    prompt = researchers.researcher_prompt(created["id"], "Review this paper.")
    assert "<reviewer_instructions>" in prompt
    assert "Be rigorous." in prompt
    assert 'name="methods.md"' in prompt
    assert "## Methods" in prompt
    assert "verbatim quote and anchor" in prompt
