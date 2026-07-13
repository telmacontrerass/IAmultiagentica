from ci2lab.harness.tools.arg_normalize import normalize_args_for_tool
from ci2lab.harness.tools.executor_parts.arguments import normalize_tool_arguments


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


def test_web_search_maps_raw_to_query():
    args = normalize_args_for_tool(
        "web_search",
        {"raw": "yesterday's soccer match Spain score", "max_results": "3"},
    )
    assert args["query"] == "yesterday's soccer match Spain score"
    assert args["max_results"] == 3
    assert "raw" not in args


def test_strips_surrounding_quotes_from_path():
    # Single quotes (the exact bug: a leading quote made the abs path look relative).
    args = normalize_args_for_tool("read_document", {"path": "'/abs/My File.pdf'"})
    assert args["path"] == "/abs/My File.pdf"
    # Double quotes on a relative path.
    args = normalize_args_for_tool("read_file", {"path": '"./rel.py"'})
    assert args["path"] == "./rel.py"
    # Backticks on a url.
    args = normalize_args_for_tool("web_fetch", {"url": "`http://example.com`"})
    assert args["url"] == "http://example.com"
    # An aliased key is stripped and still mapped to path.
    args = normalize_args_for_tool("read_file", {"filename": "'data.csv'"})
    assert args["path"] == "data.csv"


def test_unquoted_path_is_left_untouched():
    args = normalize_args_for_tool("read_document", {"path": "/abs/My File.pdf"})
    assert args["path"] == "/abs/My File.pdf"


# --- Boolean coercion (via the schema-aware normalize_tool_arguments) ---


def test_string_false_coerces_to_bool_false():
    # The bug: "false" is a truthy non-empty string, so edit_file would replace
    # ALL occurrences despite the model asking not to.
    args = normalize_tool_arguments({"replace_all": "false"}, tool_name="edit_file")
    assert args["replace_all"] is False


def test_string_true_coerces_to_bool_true():
    args = normalize_tool_arguments({"replace_all": "true"}, tool_name="edit_file")
    assert args["replace_all"] is True


def test_numeric_string_booleans_coerce():
    assert normalize_tool_arguments({"ignore_case": "0"}, tool_name="grep")["ignore_case"] is False
    assert normalize_tool_arguments({"ignore_case": "1"}, tool_name="grep")["ignore_case"] is True


def test_boolean_coercion_covers_all_declared_boolean_args():
    assert normalize_tool_arguments({"staged": "no"}, tool_name="git_diff")["staged"] is False
    assert (
        normalize_tool_arguments({"overwrite": "yes"}, tool_name="write_pptx")["overwrite"] is True
    )


def test_real_bool_is_left_untouched():
    args = normalize_tool_arguments({"replace_all": True}, tool_name="edit_file")
    assert args["replace_all"] is True


def test_non_boolean_argument_is_not_coerced():
    # `content` is a string field: the literal text "false" must survive intact.
    args = normalize_tool_arguments({"path": "a.txt", "content": "false"}, tool_name="write_file")
    assert args["content"] == "false"


def test_unrecognized_boolean_string_is_left_untouched():
    args = normalize_tool_arguments({"replace_all": "maybe"}, tool_name="edit_file")
    assert args["replace_all"] == "maybe"


# --- Integer coercion (via the schema-aware normalize_tool_arguments) ---


def test_digit_string_coerces_to_int_for_uncovered_tool():
    # tree.depth had no hand-written coercion: "2" reaching range()/comparisons
    # blew up cryptically. Schema-driven coercion now fixes it.
    args = normalize_tool_arguments({"path": ".", "depth": "2"}, tool_name="tree")
    assert args["depth"] == 2
    assert isinstance(args["depth"], int)


def test_inspect_file_integers_coerce():
    args = normalize_tool_arguments(
        {"path": "a.py", "start": "3", "max_lines": "80"}, tool_name="inspect_file"
    )
    assert args["start"] == 3
    assert args["max_lines"] == 80


def test_real_int_is_left_untouched():
    args = normalize_tool_arguments({"path": ".", "depth": 2}, tool_name="tree")
    assert args["depth"] == 2


def test_non_digit_string_on_int_arg_is_left_untouched():
    args = normalize_tool_arguments({"path": ".", "depth": "deep"}, tool_name="tree")
    assert args["depth"] == "deep"


def test_non_integer_argument_is_not_coerced():
    # `content` is a string field: a digit-only value must stay a string.
    args = normalize_tool_arguments({"path": "a.txt", "content": "5"}, tool_name="write_file")
    assert args["content"] == "5"
