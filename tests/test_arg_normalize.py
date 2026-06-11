from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool


def test_write_file_maps_new_string_to_content():
    args = normalize_args_for_tool("write_file", {"path": "a.py", "new_string": "hello"})
    assert args["content"] == "hello"
    assert "new_string" not in args


def test_bash_maps_cmd_to_command():
    args = normalize_args_for_tool("bash", {"cmd": "python app.py"})
    assert args["command"] == "python app.py"


def test_read_file_coerces_numeric_strings():
    args = normalize_args_for_tool(
        "read_file",
        {"path": "a.py", "offset": "10", "limit": "50"},
    )
    assert args["offset"] == 10
    assert args["limit"] == 50
