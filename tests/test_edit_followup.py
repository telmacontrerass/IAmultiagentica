from pathlib import Path

from ci2lab.harness.edit_followup import process_edit_round, stale_old_string_hint
from ci2lab.harness.types import ToolCall, ToolResult


def test_edit_followup_mentions_user_file_when_path_missing():
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: file does not exist: C:\\proj\\src\\main.py",
            is_error=True,
        )
    ]
    followup = process_edit_round(
        [ToolCall(name="edit_file", arguments={"path": "src/main.py"})],
        results,
        cwd=".",
        user_prompt="read sample.py and change line 3",
        completed_edits=set(),
    )
    assert followup is not None
    assert "sample.py" in followup
    assert "src/main.py" in followup


def test_success_followup_after_edit_file(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("line three\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "sample.py",
                "old_string": "line three",
                "new_string": "fourteenth attempt",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content=f"Edited {target}: 1 replacement(s)",
            is_error=False,
        )
    ]
    completed: set[tuple[str, str, str]] = set()

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change line 3 of sample.py",
        completed_edits=completed,
    )

    assert followup is not None
    assert "applied successfully" in followup
    assert ("sample.py", "line three", "fourteenth attempt") in completed


def test_redundant_edit_followup_when_change_already_in_file(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("fourteenth attempt\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "sample.py",
                "old_string": "line three",
                "new_string": "fourteenth attempt",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string not found in the file",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change sample.py",
        completed_edits=set(),
    )

    assert followup is not None
    assert "already applied" in followup
    assert "Call read_file again" not in followup


def test_redundant_edit_followup_when_recorded_in_session(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("fourteenth attempt\n", encoding="utf-8")
    sig = ("sample.py", "line three", "fourteenth attempt")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": sig[0],
                "old_string": sig[1],
                "new_string": sig[2],
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string not found in the file",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change sample.py",
        completed_edits={sig},
    )

    assert followup is not None
    assert "already applied" in followup


def test_stale_old_string_hint_shows_current_file_content(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text(
        "# sample file\nline two\nfourteenth attempt\nline four\n",
        encoding="utf-8",
    )

    hint = stale_old_string_hint(str(tmp_path), "sample.py", "line three")

    assert hint is not None
    assert "fourteenth attempt" in hint
    assert "is no longer" in hint


def test_stale_old_string_followup_on_failed_edit(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("fourteenth attempt\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "sample.py",
                "old_string": "line three",
                "new_string": "some other attempt",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string not found in the file",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change sample.py line 3",
        completed_edits=set(),
    )

    assert followup is not None
    assert "fourteenth attempt" in followup
    assert "already applied" not in followup


def test_missing_old_string_still_suggests_read_file(tmp_path: Path):
    target = tmp_path / "a.txt"
    target.write_text("different content\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "a.txt",
                "old_string": "does not exist here",
                "new_string": "new",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string not found in the file",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="edit a.txt",
        completed_edits=set(),
    )

    assert followup is not None
    assert "read_file" in followup
    assert "already applied" not in followup
