import base64
import sqlite3
from pathlib import Path

from ci2lab.harness.session import load_session, save_session
from ci2lab.ui import projects


def _use_temp_projects(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    monkeypatch.setattr(projects, "projects_root", lambda: root)
    root.mkdir()
    return root


def test_projects_have_independent_sqlite_databases(monkeypatch, tmp_path):
    root = _use_temp_projects(monkeypatch, tmp_path)

    physics = projects.create_project("Physics 2")
    history = projects.create_project("History")

    assert physics["ok"] is True
    assert history["ok"] is True
    assert physics["project"]["id"] != history["project"]["id"]
    assert (root / physics["project"]["id"] / "project.sqlite3").is_file()
    assert (root / history["project"]["id"] / "project.sqlite3").is_file()


def test_project_sources_are_persistent_and_isolated(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    physics = projects.create_project("Physics")["project"]
    history = projects.create_project("History")["project"]

    source = projects.add_project_source(
        physics["id"],
        {
            "name": "notes.txt",
            "content_base64": base64.b64encode(
                b"Newton's second law states that force equals mass times acceleration."
            ).decode(),
        },
    )

    assert source["ok"] is True
    assert len(projects.list_project_sources(physics["id"])["sources"]) == 1
    assert projects.list_project_sources(history["id"])["sources"] == []
    assert "mass times acceleration" in projects.project_context(
        physics["id"], "How are force and acceleration related?"
    )
    assert projects.project_context(history["id"], "force acceleration") == ""


def test_contradictory_sources_never_cross_project_boundary(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    group_a = projects.create_project("Class A")["project"]
    group_b = projects.create_project("Class B")["project"]
    projects.add_project_source(
        group_a["id"],
        {
            "name": "grading-policy.txt",
            "content_base64": base64.b64encode(
                b"The final exam is graded out of 10 and calculators are allowed."
            ).decode(),
        },
    )
    projects.add_project_source(
        group_b["id"],
        {
            "name": "grading-policy.txt",
            "content_base64": base64.b64encode(
                b"The final exam is graded out of 100 and calculators are forbidden."
            ).decode(),
        },
    )

    prompt_a = projects.project_prompt(group_a["id"], "How is the final exam graded?")
    prompt_b = projects.project_prompt(group_b["id"], "How is the final exam graded?")

    assert "out of 10 and calculators" in prompt_a
    assert "calculators are allowed" in prompt_a
    assert "out of 100 and calculators" not in prompt_a
    assert "calculators are forbidden" not in prompt_a
    assert "out of 100 and calculators" in prompt_b
    assert "calculators are forbidden" in prompt_b
    assert "out of 10 and calculators" not in prompt_b
    assert "calculators are allowed" not in prompt_b


def test_source_rows_are_tagged_with_their_own_project_id(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    project = projects.create_project("Chemistry")["project"]
    projects.add_project_source(
        project["id"],
        {
            "name": "atoms.txt",
            "content_base64": base64.b64encode(b"Atoms contain protons.").decode(),
        },
    )

    with sqlite3.connect(Path(project["workspace"]) / "project.sqlite3") as db:
        stored_project_id = db.execute(
            "SELECT project_id FROM sources"
        ).fetchone()[0]

    assert stored_project_id == project["id"]


def test_source_cannot_be_deleted_through_another_project(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    first = projects.create_project("First")["project"]
    second = projects.create_project("Second")["project"]
    added = projects.add_project_source(
        first["id"],
        {
            "name": "private.txt",
            "content_base64": base64.b64encode(b"Only the first project knows this.").decode(),
        },
    )

    rejected = projects.delete_project_source(second["id"], added["source"]["id"])

    assert rejected["ok"] is False
    assert len(projects.list_project_sources(first["id"])["sources"]) == 1
    assert projects.list_project_sources(second["id"])["sources"] == []


def test_project_path_rejects_traversal(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)

    assert projects.project_dir("../another-project") is None
    assert projects.project_context("../another-project", "secret") == ""


def test_deleting_project_also_removes_its_conversations(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: sessions)
    project = projects.create_project("Literature")["project"]
    save_session(
        "literature-chat",
        messages=[{"role": "user", "content": "Discuss the novel"}],
        model_tag="model:1b",
        cwd=project["workspace"],
        project_id=project["id"],
    )

    result = projects.delete_project(project["id"])

    assert result["ok"] is True
    assert load_session("literature-chat") is None


def test_project_prompt_identifies_sources(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    project = projects.create_project("Calculus")["project"]
    projects.add_project_source(
        project["id"],
        {
            "name": "slides.md",
            "content_base64": base64.b64encode(
                b"The derivative measures the instantaneous rate of change."
            ).decode(),
        },
    )

    prompt = projects.project_prompt(project["id"], "Explain the derivative")

    assert "Calculus" in prompt
    assert "slides.md" in prompt
    assert "instantaneous rate of change" in prompt


def test_deleting_source_removes_only_that_project_file(monkeypatch, tmp_path):
    _use_temp_projects(monkeypatch, tmp_path)
    project = projects.create_project("Biology")["project"]
    added = projects.add_project_source(
        project["id"],
        {
            "name": "cells.txt",
            "content_base64": base64.b64encode(b"Cells are the basic unit of life.").decode(),
        },
    )
    source = added["source"]
    stored = Path(project["workspace"]) / source["path"]

    result = projects.delete_project_source(project["id"], source["id"])

    assert result["ok"] is True
    assert not stored.exists()
    assert projects.list_project_sources(project["id"])["sources"] == []
