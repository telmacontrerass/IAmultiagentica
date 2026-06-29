"""Harness robustness: shell command translation, skill allow-lists, and grep
fallback for invalid regexes.

Covers the regressions seen with local models (qwen) in restricted mode: the
model insists on `bash ls`/`bash grep`/`ls` even though the skill only allows
`list_files`/`grep`, and gets stuck in a loop. Those commands are now translated
to the allowed tool instead of being blocked.
"""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.bash_redirect import shell_command_to_tool
from ci2lab.harness.tools.filesystem_parts.browse import grep_search
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall

# ---------------------------------------------------------------------------
# shell_command_to_tool: translation of POSIX commands to tools
# ---------------------------------------------------------------------------


def test_ls_dir_translates_to_ls_tool():
    call = shell_command_to_tool("ls Test/")
    assert call is not None
    assert call.name == "ls"
    assert call.arguments["path"] == "Test/"


def test_ls_with_glob_translates_to_glob_tool():
    call = shell_command_to_tool("ls Test/*.docx")
    assert call is not None
    assert call.name == "glob"
    assert call.arguments["pattern"] == "Test/*.docx"


def test_grep_translates_to_grep_tool():
    call = shell_command_to_tool('grep -i "Test"')
    assert call is not None
    assert call.name == "grep"
    assert call.arguments["pattern"] == "Test"
    assert call.arguments.get("ignore_case") is True


def test_find_name_translates_to_glob():
    call = shell_command_to_tool("find . -name *.docx")
    assert call is not None
    assert call.name == "glob"
    assert call.arguments["pattern"] == "**/*.docx"


def test_cat_translates_to_read_file():
    call = shell_command_to_tool("cat report.txt")
    assert call is not None
    assert call.name == "read_file"
    assert call.arguments["path"] == "report.txt"


def test_bare_glob_command_translates_to_glob_tool():
    # The model wrote `bash glob **/x` and got "glob: not found".
    call = shell_command_to_tool("glob **/*.docx")
    assert call is not None
    assert call.name == "glob"
    assert call.arguments["pattern"] == "**/*.docx"


def test_pipeline_uses_first_segment():
    call = shell_command_to_tool('ls | grep "Test"')
    assert call is not None
    assert call.name == "ls"


def test_complex_shell_not_translated():
    assert shell_command_to_tool("cd foo && ls") is None
    assert shell_command_to_tool("echo hi > out.txt") is None
    assert shell_command_to_tool("python script.py") is None


# ---------------------------------------------------------------------------
# Skill allow-list: synonyms and translation of blocked bash
# ---------------------------------------------------------------------------

_RESEARCHER_TOOLS = frozenset({"grep", "list_files", "read_document", "read_file"})


def test_ls_allowed_when_skill_lists_list_files(tmp_path: Path):
    (tmp_path / "Test").mkdir()
    (tmp_path / "Test" / "doc.docx").write_bytes(b"x")
    cfg = AgentConfig(cwd=str(tmp_path), skill_allowed_tools=_RESEARCHER_TOOLS)
    # The skill allows `list_files`, the model calls `ls`: it must be allowed.
    result = execute_tool(ToolCall(name="ls", arguments={"path": "Test"}), cfg)
    assert not result.is_error
    assert "doc.docx" in result.content


def test_bash_ls_redirected_under_restricted_skill(tmp_path: Path):
    (tmp_path / "Test").mkdir()
    (tmp_path / "Test" / "doc.docx").write_bytes(b"x")
    cfg = AgentConfig(cwd=str(tmp_path), skill_allowed_tools=_RESEARCHER_TOOLS)
    # `bash` is not allowed, but `bash ls Test` must be translated to `ls`.
    result = execute_tool(ToolCall(name="bash", arguments={"command": "ls Test"}), cfg)
    assert not result.is_error
    assert "doc.docx" in result.content


def test_blocked_tool_message_suggests_alternative(tmp_path: Path):
    cfg = AgentConfig(cwd=str(tmp_path), skill_allowed_tools=_RESEARCHER_TOOLS)
    # write_file is not allowed and has no equivalent: clear message, no loop.
    result = execute_tool(
        ToolCall(name="write_file", arguments={"path": "x.txt", "content": "y"}),
        cfg,
    )
    assert result.is_error
    assert "not allowed by the active skill" in result.content


# ---------------------------------------------------------------------------
# grep: fallback for patterns that are not valid regexes (glob style)
# ---------------------------------------------------------------------------


def test_grep_invalid_regex_falls_back_to_literal(tmp_path: Path):
    (tmp_path / "a.txt").write_text("contains **/*.docx here", encoding="utf-8")
    # `**/*.docx` is not a valid regex ("multiple repeat"): it used to raise Error.
    result = grep_search(str(tmp_path), "**/*.docx")
    assert not result.startswith("Error:")
    assert "a.txt" in result
    assert "glob" in result  # note suggesting to use the glob tool
