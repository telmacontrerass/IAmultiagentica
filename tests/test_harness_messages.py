from ci2lab.harness.messages import append_assistant_turn
from ci2lab.harness.types import ToolCall


def test_append_assistant_turn_uses_empty_string_for_tool_only_turns():
    messages = []

    append_assistant_turn(
        messages,
        "",
        [ToolCall(name="read_document", arguments={"path": "prueba.pdf"})],
    )

    assert messages[0]["content"] == ""
    assert messages[0]["tool_calls"][0]["function"]["name"] == "read_document"
