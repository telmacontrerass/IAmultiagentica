from ci2lab.harness.parsing import (
    parse_fenced_blocks,
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


def test_strip_markup():
    text = "Hola\n```bash\necho hi\n```\n<invoke name=\"ls\"><parameter name=\"path\">.</parameter></invoke>"
    cleaned = strip_tool_markup(text)
    assert "bash" not in cleaned
    assert "invoke" not in cleaned
    assert "Hola" in cleaned
