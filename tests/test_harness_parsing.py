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
from ci2lab.harness.parsing_parts.common import map_name


def test_resolver_records_actual_protocol_and_parser():
    native = [{"id": "n1", "function": {"name": "read_file", "arguments": '{"path":"a"}'}}]
    cases = [
        ("", native, "native", "native"),
        (
            '<invoke name="read_file"><parameter name="path">a</parameter></invoke>',
            [],
            "xml",
            "xml_blocks",
        ),
        ("```read_file\na\n```", [], "fenced", "fenced_blocks"),
        ('{"name":"read_file","arguments":{"path":"a"}}', [], "json", "json_objects"),
        ('bash\n{"cwd":"."}', [], "name_plus_json", "text_name_plus_json"),
        ("```sh\necho hi\n```", [], "generic_block", "generic_fenced_blocks"),
    ]
    for text, native_calls, protocol, parser_id in cases:
        call = resolve_tool_calls(text, native_calls, tool_mode="native")[0]
        assert call.source_protocol == protocol
        assert call.parser_id == parser_id


def test_parse_fenced_bash():
    text = "I am going to list.\n```bash\nls -la\n```"
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


def test_pptx_aliases_map_to_write_pptx():
    for alias in ("presentation", "pptx", "deck", "slides", "diapositivas", "presentacion"):
        assert map_name(alias) == "write_pptx"


def test_bare_json_pptx_payload_infers_write_pptx():
    calls = parse_json_tool_objects(
        '{"output_path": "outputs/deck.pptx", "title": "Deck", '
        '"slides": [{"type": "cover", "title": "Deck"}]}'
    )
    assert len(calls) == 1
    assert calls[0].name == "write_pptx"
    assert calls[0].arguments["output_path"] == "outputs/deck.pptx"


def test_parse_xml_invoke():
    text = '<invoke name="bash"><parameter name="command">echo hi</parameter></invoke>'
    calls = parse_xml_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "bash"
    assert calls[0].arguments["command"] == "echo hi"


def test_parse_function_dialect_orphan_close():
    # Qwen-Coder emits <function=NAME>/<parameter=KEY> with an orphan </tool_call>
    # close (no opener). Regression for the qa-02 leak where the call never ran.
    text = (
        "Let me explore.\n\n"
        "<function=ls>\n<parameter=path>\n.\n</parameter>\n</function>\n</tool_call>"
    )
    calls = parse_xml_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "ls"
    assert calls[0].arguments["path"] == "."


def test_parse_function_dialect_multiple_params():
    text = (
        "<function=write_file>"
        "<parameter=path>summary.txt</parameter>"
        "<parameter=content>hello world</parameter>"
        "</function>"
    )
    calls = parse_xml_blocks(text)
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "summary.txt"
    assert calls[0].arguments["content"] == "hello world"


def test_function_dialect_resolves_and_strips():
    text = "Prose before.\n<function=ls>\n<parameter=path>.</parameter>\n</function>\n</tool_call>"
    assert resolve_tool_calls(text, [], tool_mode="native")[0].name == "ls"
    cleaned = strip_tool_markup(text)
    assert cleaned == "Prose before."
    assert "function" not in cleaned and "tool_call" not in cleaned


def test_standard_invoke_still_parses_after_function_normalization():
    # The <function=…> normalization must not disturb the standard <invoke> form.
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
    native = [
        {
            "id": "c1",
            "function": {
                "name": "read_file",
                "arguments": {"path": "config.txt", "offset": None, "limit": None},
            },
        }
    ]
    calls = resolve_tool_calls("", native, tool_mode="native")
    assert calls[0].arguments == {"path": "config.txt"}


def test_strip_markup():
    text = 'Hello\n```bash\necho hi\n```\n<invoke name="ls"><parameter name="path">.</parameter></invoke>'
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
        "```json\n"
        "{\n"
        '  "path": "Tests.py",\n'
        '  "old_string": "line three",\n'
        '  "new_string": "I don\'t know how many attempts"\n'
        "}\n"
        "```"
    )
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["new_string"] == "I don't know how many attempts"


def test_parse_json_fenced_command_args_edit_file():
    text = (
        "```json\n"
        "{\n"
        '  "command": "edit_file",\n'
        '  "args": {\n'
        '    "path": "Tests.py",\n'
        '    "old_string": "line three",\n'
        '    "new_string": "I don\'t know how many attempts"\n'
        "  }\n"
        "}\n"
        "```"
    )
    calls = resolve_tool_calls(text, [], tool_mode="fenced")
    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments["path"] == "Tests.py"
    assert calls[0].arguments["old_string"] == "line three"


def test_parse_json_fenced_write_file():
    text = (
        "Here is the tool call:\n```json\n"
        '{"name": "write_file", "arguments": {"path": "count_to_100.py", '
        '"content": "for i in range(1, 101):\\n    print(i)\\n"}}\n```'
    )
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "count_to_100.py"
    assert "print(i)" in calls[0].arguments["content"]


def test_parse_inline_json_write_file():
    text = '{"name": "write_file", "arguments": {"path": "wordle.py", "content": "print(1)"}}'
    calls = parse_json_tool_objects(text)
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "wordle.py"


def test_parse_llama_parameters_field():
    text = (
        '{"name": "read_file", "parameters": {"path": "wordle.py", "offset": "1", "limit": "1000"}}'
    )
    calls = resolve_tool_calls(text, [], tool_mode="native")
    assert calls[0].name == "read_file"
    assert calls[0].arguments["path"] == "wordle.py"
    assert calls[0].arguments["offset"] == 1
    assert calls[0].arguments["limit"] == 1000


def test_parse_llama_nested_tool_calls_with_parameters():
    text = (
        '{"tool_calls": [{"name": "write_file", "parameters": '
        '{"path": "notes/example.txt", "content": "OK"}}]}'
    )
    calls = parse_json_tool_objects(text)
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments["path"] == "notes/example.txt"
    assert calls[0].arguments["content"] == "OK"


def test_parse_write_file_inside_bash_fence():
    text = '```bash\nwrite_file\n{"path": "wordle.py", "content": "print(1)"}\n```'
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
        ("```note\npython -c \"print('BAD')\"\n```", "note"),
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
    native = [
        {
            "name": "write_file",
            "arguments": {"path": "a.py", "new_string": "x = 1"},
        }
    ]
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


def test_fenced_json_args_with_regex_escapes_are_repaired():
    # Models embed regexes in JSON without doubling the backslash
    # (`{"pattern": "ERR-\d{4}"}` is invalid JSON). The parser must recover the
    # intended arguments instead of degrading to a junk literal pattern.
    from ci2lab.harness.parsing import resolve_tool_calls

    text = '```grep\n{"pattern": "ERR-\\d{4}", "path": "app.log"}\n```'
    calls = resolve_tool_calls(text, None, tool_mode="fenced")

    assert len(calls) == 1
    assert calls[0].name == "grep"
    assert calls[0].arguments["pattern"] == r"ERR-\d{4}"
    assert calls[0].arguments["path"] == "app.log"


def test_native_function_arguments_with_regex_escapes_are_repaired():
    from ci2lab.harness.parsing import resolve_tool_calls

    native = [
        {
            "id": "c1",
            "function": {
                "name": "grep",
                "arguments": r'{"pattern": "code=\w+", "path": "app.log"}',
            },
        }
    ]
    calls = resolve_tool_calls("", native, tool_mode="native")

    assert len(calls) == 1
    assert calls[0].arguments["pattern"] == r"code=\w+"
