import json
import subprocess

from ci2lab.harness.tools.ask_user import ask_user
from ci2lab.harness.tools.git_tools import git_diff, git_status
from ci2lab.harness.tools.notebook import notebook_edit
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.tools.todo import open_todos, todo_read, todo_write
from ci2lab.harness.tools.web import web_fetch
from ci2lab.harness.types import AgentConfig, ToolCall


def test_todo_write_and_read(tmp_path):
    out = todo_write(
        str(tmp_path),
        [
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second", "status": "in_progress"},
        ],
    )
    assert "2 items" in out
    saved = json.loads(todo_read(str(tmp_path)))
    assert len(saved) == 2
    assert saved[1]["status"] == "in_progress"


def test_todo_write_rejects_empty(tmp_path):
    assert todo_write(str(tmp_path), []).startswith("Error:")


def test_todo_write_result_points_at_next_step(tmp_path):
    out = todo_write(
        str(tmp_path),
        [
            {"id": "1", "content": "read the file", "status": "in_progress"},
            {"id": "2", "content": "write the change", "status": "pending"},
        ],
    )
    # The result must drive the model on instead of reading like a stop point.
    assert "read the file" in out
    assert "2 step(s) remain" in out
    assert "do not stop" in out.lower()


def test_todo_write_result_prompts_final_answer_when_all_done(tmp_path):
    out = todo_write(
        str(tmp_path),
        [{"id": "1", "content": "do it", "status": "completed"}],
    )
    assert "All steps are completed" in out
    assert "final result" in out.lower()


def test_open_todos_returns_only_unfinished(tmp_path):
    todo_write(
        str(tmp_path),
        [
            {"id": "1", "content": "a", "status": "completed"},
            {"id": "2", "content": "b", "status": "pending"},
            {"id": "3", "content": "c", "status": "in_progress"},
            {"id": "4", "content": "d", "status": "cancelled"},
        ],
    )
    open_items = open_todos(str(tmp_path))
    assert [t["content"] for t in open_items] == ["b", "c"]


def test_open_todos_empty_when_no_file(tmp_path):
    assert open_todos(str(tmp_path)) == []


def test_ask_user_free_text(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "python 3.12")
    assert ask_user("Which version?") == "python 3.12"


def test_ask_user_numbered_option(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
    assert ask_user("Pick one", options=["a", "b"]) == "b"


def test_web_fetch_rejects_non_http():
    assert "only http" in web_fetch("file:///etc/passwd").lower()


def test_web_fetch_success(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = "hello docs"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url.startswith("https://")
            return FakeResponse()

    monkeypatch.setattr("ci2lab.harness.tools.web.httpx.Client", FakeClient)
    out = web_fetch("https://example.com/doc")
    assert "hello docs" in out
    assert "example.com" in out


def test_notebook_edit_cell(tmp_path):
    nb = {
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": ["x = 1\n"], "outputs": []},
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path = tmp_path / "test.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")

    out = notebook_edit(str(tmp_path), "test.ipynb", 0, "print('hi')\n", "code")
    assert "Edited" in out

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["cells"][0]["source"] == ["print('hi')\n"]
    assert updated["cells"][0]["outputs"] == []


def test_git_status_in_repo(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    out = git_status(str(tmp_path))
    assert "a.txt" in out or "??" in out


def test_git_diff_shows_changes(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    out = git_diff(str(tmp_path), path="a.txt")
    assert "hello" in out


def test_execute_todo_write_via_registry(tmp_path):
    call = ToolCall(
        name="todo_write",
        arguments={
            "todos": [{"content": "Ship feature", "status": "pending"}],
        },
        call_id="t1",
    )
    result = execute_tool(call, AgentConfig(cwd=str(tmp_path), auto_confirm=True))
    assert not result.is_error
    assert (tmp_path / ".ci2lab" / "todos.json").is_file()
