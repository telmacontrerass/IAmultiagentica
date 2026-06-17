"""Robustez del arnés: traducción de comandos de shell, allow-lists de skills,
y fallback de grep ante regex inválidas.

Cubre las regresiones vistas con modelos locales (qwen) en modo restringido:
el modelo insiste en `bash ls`/`bash grep`/`ls` aunque el skill solo permita
`list_files`/`grep`, y entra en bucle. Ahora esos comandos se traducen al tool
permitido en vez de bloquearse.
"""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.bash_redirect import shell_command_to_tool
from ci2lab.harness.tools.filesystem_parts.browse import grep_search
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall


# ---------------------------------------------------------------------------
# shell_command_to_tool: traducción de comandos POSIX a tools
# ---------------------------------------------------------------------------

def test_ls_dir_translates_to_ls_tool():
    call = shell_command_to_tool("ls Prueba/")
    assert call is not None
    assert call.name == "ls"
    assert call.arguments["path"] == "Prueba/"


def test_ls_with_glob_translates_to_glob_tool():
    call = shell_command_to_tool("ls Prueba/*.docx")
    assert call is not None
    assert call.name == "glob"
    assert call.arguments["pattern"] == "Prueba/*.docx"


def test_grep_translates_to_grep_tool():
    call = shell_command_to_tool('grep -i "Prueba"')
    assert call is not None
    assert call.name == "grep"
    assert call.arguments["pattern"] == "Prueba"
    assert call.arguments.get("ignore_case") is True


def test_find_name_translates_to_glob():
    call = shell_command_to_tool("find . -name *.docx")
    assert call is not None
    assert call.name == "glob"
    assert call.arguments["pattern"] == "**/*.docx"


def test_cat_translates_to_read_file():
    call = shell_command_to_tool("cat informe.txt")
    assert call is not None
    assert call.name == "read_file"
    assert call.arguments["path"] == "informe.txt"


def test_bare_glob_command_translates_to_glob_tool():
    # El modelo escribió `bash glob **/x` y obtuvo "glob: not found".
    call = shell_command_to_tool("glob **/*.docx")
    assert call is not None
    assert call.name == "glob"
    assert call.arguments["pattern"] == "**/*.docx"


def test_pipeline_uses_first_segment():
    call = shell_command_to_tool('ls | grep "Prueba"')
    assert call is not None
    assert call.name == "ls"


def test_complex_shell_not_translated():
    assert shell_command_to_tool("cd foo && ls") is None
    assert shell_command_to_tool("echo hi > out.txt") is None
    assert shell_command_to_tool("python script.py") is None


# ---------------------------------------------------------------------------
# Allow-list de skill: sinónimos y traducción de bash bloqueado
# ---------------------------------------------------------------------------

_RESEARCHER_TOOLS = frozenset({"grep", "list_files", "read_document", "read_file"})


def test_ls_allowed_when_skill_lists_list_files(tmp_path: Path):
    (tmp_path / "Prueba").mkdir()
    (tmp_path / "Prueba" / "doc.docx").write_bytes(b"x")
    cfg = AgentConfig(cwd=str(tmp_path), skill_allowed_tools=_RESEARCHER_TOOLS)
    # El skill permite `list_files`, el modelo llama `ls`: debe permitirse.
    result = execute_tool(ToolCall(name="ls", arguments={"path": "Prueba"}), cfg)
    assert not result.is_error
    assert "doc.docx" in result.content


def test_bash_ls_redirected_under_restricted_skill(tmp_path: Path):
    (tmp_path / "Prueba").mkdir()
    (tmp_path / "Prueba" / "doc.docx").write_bytes(b"x")
    cfg = AgentConfig(cwd=str(tmp_path), skill_allowed_tools=_RESEARCHER_TOOLS)
    # `bash` no está permitido, pero `bash ls Prueba` debe traducirse a `ls`.
    result = execute_tool(
        ToolCall(name="bash", arguments={"command": "ls Prueba"}), cfg
    )
    assert not result.is_error
    assert "doc.docx" in result.content


def test_blocked_tool_message_suggests_alternative(tmp_path: Path):
    cfg = AgentConfig(cwd=str(tmp_path), skill_allowed_tools=_RESEARCHER_TOOLS)
    # write_file no está permitido ni tiene equivalente: mensaje claro, no bucle.
    result = execute_tool(
        ToolCall(name="write_file", arguments={"path": "x.txt", "content": "y"}),
        cfg,
    )
    assert result.is_error
    assert "not allowed by the active skill" in result.content


# ---------------------------------------------------------------------------
# grep: fallback ante patrones que no son regex válidas (estilo glob)
# ---------------------------------------------------------------------------

def test_grep_invalid_regex_falls_back_to_literal(tmp_path: Path):
    (tmp_path / "a.txt").write_text("contiene **/*.docx aqui", encoding="utf-8")
    # `**/*.docx` no es regex válida ("multiple repeat"): antes daba Error.
    result = grep_search(str(tmp_path), "**/*.docx")
    assert not result.startswith("Error:")
    assert "a.txt" in result
    assert "glob" in result  # nota que sugiere usar la herramienta glob
