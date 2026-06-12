from ci2lab.harness.tools.bash_redirect import tool_call_from_bash_command
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.parsing import parse_generic_fenced_blocks, resolve_tool_calls
from ci2lab.harness.types import AgentConfig, ToolCall


def test_bash_command_read_file_redirects_to_tool_call():
    call = tool_call_from_bash_command("read_file Pruebas.py")
    assert call is not None
    assert call.name == "read_file"
    assert call.arguments["path"] == "Pruebas.py"


def test_bash_command_edit_file_redirects_to_tool_call():
    call = tool_call_from_bash_command(
        'edit_file {"path": "Pruebas.py", "old_string": "a", "new_string": "b"}'
    )
    assert call is not None
    assert call.name == "edit_file"
    assert call.arguments["path"] == "Pruebas.py"


def test_execute_bash_read_file_runs_read_file(tmp_path):
    target = tmp_path / "Pruebas.py"
    target.write_text("hola\n", encoding="utf-8")
    config = AgentConfig(cwd=str(tmp_path), auto_confirm=True)

    result = execute_tool(
        ToolCall(name="bash", arguments={"command": "read_file Pruebas.py"}),
        config,
    )

    assert not result.is_error
    assert result.tool_name == "read_file"
    assert "hola" in result.content


def test_parse_bash_fence_with_read_file_path():
    text = "```bash\nread_file Pruebas.py\n```"
    calls = parse_generic_fenced_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments["path"] == "Pruebas.py"


def test_resolve_fenced_read_file_not_as_bash():
    text = "```bash\nread_file Pruebas.py\n```"
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "read_file"
