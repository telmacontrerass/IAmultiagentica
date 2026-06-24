import pytest

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
    text = 'I am going to list.\n```bash\nls -la\n```'
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


def test_parse_fenced_web_search_plain_query():
    calls = parse_fenced_blocks("```web_search\nyesterday's soccer match Spain score\n```")
    assert calls[0].name == "web_search"
    assert calls[0].arguments["query"] == "yesterday's soccer match Spain score"


def test_parse_fenced_docx_to_pdf_json_args():
    calls = parse_fenced_blocks(
        '```docx_to_pdf\n{"source": "Test/report.docx", "output": "Test/report.pdf"}\n```'
    )
    assert calls[0].name == "docx_to_pdf"
    assert calls[0].arguments["source"] == "Test/report.docx"
    assert calls[0].arguments["output"] == "Test/report.pdf"


def test_parse_fenced_pdf_to_docx_json_args():
    calls = parse_fenced_blocks(
        '```pdf_to_docx\n{"source": "Test/report.pdf", "output": "Test/report.docx"}\n```'
    )
    assert calls[0].name == "pdf_to_docx"
    assert calls[0].arguments["source"] == "Test/report.pdf"
    assert calls[0].arguments["output"] == "Test/report.docx"


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
    text = "Hello\n```bash\necho hi\n```\n<invoke name=\"ls\"><parameter name=\"path\">.</parameter></invoke>"
    cleaned = strip_tool_markup(text)
    assert "bash" not in cleaned
    assert "invoke" not in cleaned
    assert "Hello" in cleaned


def test_native_empty_falls_back_to_fenced():
    text = "```ls\n.\n```"
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert len(calls) == 1
    assert calls[0].name == "ls"


def test_no_tools_returns_empty():
    calls = resolve_tool_calls("just text without tools", [], tool_mode="native")
    assert calls == []


def test_parse_json_fenced_bare_edit_file_args():
    text = (
        '```json\n'
        '{\n'
        '  "path": "Tests.py",\n'
        '  "old_string": "line three",\n'
        '  "new_string": "I don\'t know how many attempts"\n'
        '}\n'
        '```'
    )
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["new_string"] == "I don't know how many attempts"


def test_parse_json_fenced_command_args_edit_file():
    text = (
        '```json\n'
        '{\n'
        '  "command": "edit_file",\n'
        '  "args": {\n'
        '    "path": "Tests.py",\n'
        '    "old_string": "line three",\n'
        '    "new_string": "I don\'t know how many attempts"\n'
        '  }\n'
        '}\n'
        '```'
    )
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "Tests.py"
    assert calls[0].arguments["old_string"] == "line three"


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


@pytest.mark.parametrize(
    ("fence_body", "tag"),
    [
        ("```unknown_tool\nx\n```", "unknown_tool"),
        ("```diagnostic\ndir\n```", "diagnostic"),
        ('```note\npython -c "print(\'BAD\')"\n```', "note"),
    ],
)
def test_v01_unknown_fenced_tags_never_become_bash(fence_body, tag):
    calls = resolve_tool_calls(fence_body, [], tool_mode="fenced")
    assert calls == [], f"{tag} must not produce tool calls"


def test_v01_json_fence_explicit_bash_is_structured_not_fallback():
    text = '```json\n{"name":"bash","arguments":{"command":"dir"}}\n```'
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "bash"
    assert calls[0].arguments["command"] == "dir"


def test_v01_plain_json_parsed_but_not_bash_fallback():
    """Inline JSON is parsed by design; V-01 is unknown fences -> bash."""
    text = '{"name":"read_file","arguments":{"path":"../secret.txt"}}'
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].name != "bash"


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


def test_unparsed_key_value_tool_attempt():
    # Regression: a model emitted the write as `write_file path='...' content='...'`
    # (key=value prose), no structured parser accepted it, and the loop mistook
    # the narration for a finished answer. It must now be flagged so the model is
    # nudged back to a real tool-call format.
    assert looks_like_unparsed_tool_attempt(
        "I will save it now.\n"
        "write_file path='examen.txt' content='[PDF page 1/6]\nConvocatoria...'"
    )
    # Function-call style is the same mistake.
    assert looks_like_unparsed_tool_attempt('read_file(path="examen.txt")')
    # Merely naming a tool in prose is NOT an attempt — no key=value follows.
    assert not looks_like_unparsed_tool_attempt(
        "You can use write_file to persist the summary to disk."
    )
