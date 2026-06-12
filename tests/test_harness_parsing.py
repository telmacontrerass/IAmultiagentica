from ci2lab.harness.parsing import (
    looks_like_unparsed_tool_attempt,
    parse_fenced_blocks,
    parse_generic_fenced_blocks,
    parse_json_tool_objects,
    parse_xml_blocks,
    resolve_tool_calls,
    strip_tool_markup,
)


def test_parse_fenced_bash():
    text = 'Voy a listar.\n```bash\nls -la\n```'
    calls = parse_fenced_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "bash"
    assert calls[0].arguments["command"] == "ls -la"


def test_parse_fenced_read_file():
    calls = parse_fenced_blocks("```read_file\nREADME.md\n```")
    assert calls[0].name == "read_file"
    assert calls[0].arguments["path"] == "README.md"


def test_parse_fenced_read_document():
    calls = parse_fenced_blocks("```read_document\nrubrica.docx\n```")
    assert calls[0].name == "read_document"
    assert calls[0].arguments["path"] == "rubrica.docx"


def test_parse_xml_invoke():
    text = '<invoke name="bash"><parameter name="command">echo hi</parameter></invoke>'
    calls = parse_xml_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "bash"
    assert calls[0].arguments["command"] == "echo hi"


def test_native_priority():
    native = [{"name": "ls", "arguments": {"path": "."}, "id": "c1"}]
    calls = resolve_tool_calls("", native, tool_mode="native")
    assert len(calls) == 1
    assert calls[0].name == "ls"


def test_native_strips_null_optional_args():
    native = [{
        "id": "c1",
        "function": {
            "name": "read_file",
            "arguments": {"path": "config.txt", "offset": None, "limit": None},
        },
    }]
    calls = resolve_tool_calls("", native, tool_mode="native")
    assert calls[0].arguments == {"path": "config.txt"}


def test_strip_markup():
    text = "Hola\n```bash\necho hi\n```\n<invoke name=\"ls\"><parameter name=\"path\">.</parameter></invoke>"
    cleaned = strip_tool_markup(text)
    assert "bash" not in cleaned
    assert "invoke" not in cleaned
    assert "Hola" in cleaned


def test_native_empty_falls_back_to_fenced():
    text = "```ls\n.\n```"
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert len(calls) == 1
    assert calls[0].name == "ls"


def test_no_tools_returns_empty():
    calls = resolve_tool_calls("solo texto sin herramientas", [], tool_mode="native")
    assert calls == []


def test_parse_json_fenced_bare_edit_file_args():
    text = (
        '```json\n'
        '{\n'
        '  "path": "Pruebas.py",\n'
        '  "old_string": "linea tres",\n'
        '  "new_string": "No se cuantos intentos"\n'
        '}\n'
        '```'
    )
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["new_string"] == "No se cuantos intentos"


def test_parse_json_fenced_command_args_edit_file():
    text = (
        '```json\n'
        '{\n'
        '  "command": "edit_file",\n'
        '  "args": {\n'
        '    "path": "Pruebas.py",\n'
        '    "old_string": "linea tres",\n'
        '    "new_string": "No se cuantos intentos"\n'
        '  }\n'
        '}\n'
        '```'
    )
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "Pruebas.py"
    assert calls[0].arguments["old_string"] == "linea tres"


def test_parse_json_fenced_write_file():
    text = (
        'Here is the tool call:\n```json\n'
        '{"name": "write_file", "arguments": {"path": "count_to_100.py", '
        '"content": "for i in range(1, 101):\\n    print(i)\\n"}}\n```'
    )
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "count_to_100.py"
    assert "print(i)" in calls[0].arguments["content"]


def test_parse_inline_json_write_file():
    text = (
        '{"name": "write_file", "arguments": {"path": "wordle.py", '
        '"content": "print(1)"}}'
    )
    calls = parse_json_tool_objects(text)
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "wordle.py"


def test_parse_llama_parameters_field():
    text = '{"name": "read_file", "parameters": {"path": "wordle.py", "offset": "1", "limit": "1000"}}'
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert calls[0].name == "read_file"
    assert calls[0].arguments["path"] == "wordle.py"
    assert calls[0].arguments["offset"] == 1
    assert calls[0].arguments["limit"] == 1000


def test_parse_write_file_inside_bash_fence():
    text = (
        "```bash\nwrite_file\n"
        '{"path": "wordle.py", "content": "print(1)"}\n```'
    )
    calls = parse_generic_fenced_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "wordle.py"


def test_parse_bash_fence_with_shell_command():
    text = "```bash\npython wordle.py\n```"
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "bash"
    assert calls[0].arguments["command"] == "python wordle.py"


def test_unknown_fenced_tag_is_not_executed_as_bash():
    calls = resolve_tool_calls("```unknown_tool\nx\n```", [], tool_mode="fenced")
    assert calls == []


def test_shell_fence_tag_still_runs_command_via_generic_parser():
    text = "```sh\necho hi\n```"
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "bash"
    assert calls[0].arguments["command"] == "echo hi"


def test_write_file_new_string_alias_normalized():
    native = [{
        "name": "write_file",
        "arguments": {"path": "a.py", "new_string": "x = 1"},
    }]
    calls = resolve_tool_calls("", native, tool_mode="native")
    assert calls[0].arguments["content"] == "x = 1"


def test_looks_like_unparsed_tool_attempt():
    # Valid JSON is now parsed successfully, so this should NOT look "unparsed".
    assert not looks_like_unparsed_tool_attempt(
        '```json\n{"name": "write_file", "arguments": {"path": "a.py", "content": "x"}}\n```'
    )
    # Broken JSON that still looks like a tool attempt should trigger recovery.
    assert looks_like_unparsed_tool_attempt(
        '```json\n{"name": "write_file", "arguments": {"path": "a.py", "content": "x"\n```'
    )
    assert not looks_like_unparsed_tool_attempt("just some explanation text")
