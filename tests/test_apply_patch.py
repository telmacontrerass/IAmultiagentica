from pathlib import Path

from ci2lab.harness.tools.patch import apply_patch, plan_patch
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall

SAMPLE_PATCH = """\
--- a/note.txt
+++ b/note.txt
@@ -1,2 +1,2 @@
 hello
-world
+ci2lab
"""


def test_apply_patch_replaces_line(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")

    result = apply_patch(str(tmp_path), SAMPLE_PATCH)

    assert result.startswith("Patch applied")
    assert target.read_text(encoding="utf-8") == "hello\nci2lab\n"


def test_apply_patch_context_mismatch(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("hello\nother\n", encoding="utf-8")

    result = apply_patch(str(tmp_path), SAMPLE_PATCH)

    assert result.startswith("Error:")
    assert "patch context not found" in result or "world" in result


def test_plan_patch_creates_new_file(tmp_path: Path):
    patch = """\
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+one
+two
"""
    plan, error = plan_patch(str(tmp_path), patch)

    assert error is None
    assert plan is not None
    assert plan.files["new.txt"] in {"one\ntwo", "one\ntwo\n"}


def test_execute_apply_patch_with_auto_confirm(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")
    config = AgentConfig(cwd=str(tmp_path), auto_confirm=True, require_diff_preview=False)

    result = execute_tool(
        ToolCall(name="apply_patch", arguments={"patch": SAMPLE_PATCH}),
        config,
    )

    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "hello\nci2lab\n"


def test_apply_patch_finds_hunk_when_header_line_is_wrong(tmp_path: Path):
    target = tmp_path / "Tests.py"
    target.write_text(
        "# test file\nline two\nline three\nline four\n",
        encoding="utf-8",
    )
    patch = """\
--- a/Tests.py
+++ b/Tests.py
@@ -2,1 +2,1 @@
-line three
+Line changed again
"""
    result = apply_patch(str(tmp_path), patch)

    assert not result.startswith("Error:")
    assert target.read_text(encoding="utf-8") == (
        "# test file\nline two\nLine changed again\nline four\n"
    )


def test_parse_fenced_apply_patch():
    from ci2lab.harness.parsing import parse_fenced_blocks

    text = """\
```apply_patch
--- a/x.txt
+++ b/x.txt
@@ -1 +1 @@
-a
+b
```
"""
    calls = parse_fenced_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "apply_patch"
    assert "--- a/x.txt" in calls[0].arguments["patch"]
