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
            "fields": "multi-agent systems, software engineering",
            "reviewing_style": "tough on methodology",
            "lens_preferences": {"methodology": "high", "format": "low", "bogus": "nope"},
        }
    )
    assert result["ok"] is True
    researcher = result["researcher"]
    assert researcher["id"].startswith("rsr_")
    assert researcher["fields"] == ["multi-agent systems", "software engineering"]
    # Only known lens keys with valid levels survive.
    assert researcher["lens_preferences"] == {"methodology": "high", "format": "low"}

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
        created["id"], {"name": "Reviewer One", "fields": ["AI safety"]}
    )
    assert updated["ok"] is True
    assert updated["researcher"]["fields"] == ["AI safety"]
    assert updated["researcher"]["created_at"] == created["created_at"]

    deleted = researchers.delete_researcher(created["id"])
    assert deleted["ok"] is True
    assert researchers.get_researcher(created["id"]) is None
    assert researchers.list_researchers() == []


def test_researcher_prompt_appends_profile_block(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    created = researchers.create_researcher(
        {"name": "Dr Ada", "fields": ["software engineering"], "reviewing_style": "rigorous"}
    )["researcher"]

    prompt = researchers.researcher_prompt(created["id"], "Review this paper.")
    assert "Review this paper." in prompt
    assert "reviewer_profile" in prompt
    assert "software engineering" in prompt
    # The profile must never be a license to invent.
    assert "verbatim quote and anchor" in prompt


def test_researcher_prompt_is_noop_without_profile(monkeypatch, tmp_path):
    _use_temp_registry(monkeypatch, tmp_path)
    assert researchers.researcher_prompt("", "hello") == "hello"
    assert researchers.researcher_prompt("rsr_missing", "hello") == "hello"
