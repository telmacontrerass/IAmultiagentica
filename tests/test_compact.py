"""Tests de compactación de contexto (micro-compact + resumen)."""

from __future__ import annotations

from ci2lab.harness.context.compact import (
    KEEP_RECENT_TOOL_RESULTS,
    SUMMARY_PREFIX,
    TOOL_RESULT_STUB,
    conservative_estimate,
    manage_context,
    micro_compact,
    should_compact,
    summarize_history,
)


def _tool_msg(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _assistant_call(call_id: str, name: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def _long(text: str = "x") -> str:
    return text * 500


class FakeResponse:
    def __init__(self, content: str, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeClient:
    def __init__(self, content: str = "summary of work", fail: bool = False):
        self._content = content
        self._fail = fail
        self.calls: list[list[dict]] = []

    def chat(self, messages, *, tools=None):
        self.calls.append(messages)
        if self._fail:
            raise RuntimeError("model offline")
        return FakeResponse(self._content)


# ---------- micro_compact ----------

def test_micro_compact_stubs_old_results_keeps_recent():
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(KEEP_RECENT_TOOL_RESULTS + 2):
        msgs.append(_assistant_call(f"c{i}", "read_file"))
        msgs.append(_tool_msg(f"c{i}", _long()))

    out, stubbed = micro_compact(msgs)

    assert stubbed == 2
    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == TOOL_RESULT_STUB
    assert tool_msgs[1]["content"] == TOOL_RESULT_STUB
    for recent in tool_msgs[2:]:
        assert recent["content"] != TOOL_RESULT_STUB


def test_micro_compact_skips_short_results():
    msgs = [
        _assistant_call("c1", "bash"),
        _tool_msg("c1", "ok"),
        *[_tool_msg(f"r{i}", _long()) for i in range(KEEP_RECENT_TOOL_RESULTS)],
    ]
    out, stubbed = micro_compact(msgs)
    assert stubbed == 0
    assert out[1]["content"] == "ok"


def test_micro_compact_never_touches_user_or_assistant():
    msgs = [
        {"role": "user", "content": _long("u")},
        {"role": "assistant", "content": _long("a")},
        *[_tool_msg(f"r{i}", _long()) for i in range(KEEP_RECENT_TOOL_RESULTS + 1)],
    ]
    out, stubbed = micro_compact(msgs)
    assert stubbed == 1
    assert out[0]["content"] == _long("u")
    assert out[1]["content"] == _long("a")


def test_micro_compact_does_not_mutate_input():
    original = _tool_msg("c1", _long())
    msgs = [original, *[_tool_msg(f"r{i}", _long()) for i in range(KEEP_RECENT_TOOL_RESULTS)]]
    micro_compact(msgs)
    assert original["content"] == _long()


# ---------- should_compact ----------

def test_should_compact_threshold():
    small = [{"role": "user", "content": "hola"}]
    assert not should_compact(small, context_length=8192)

    big = [{"role": "user", "content": "x" * 40_000}]
    assert should_compact(big, context_length=8192)


# ---------- summarize_history ----------

def _history_with_old_turns() -> list[dict]:
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(10):
        msgs.append({"role": "user", "content": f"request {i}"})
        msgs.append({"role": "assistant", "content": f"answer {i} " + "y" * 300})
    return msgs


def test_summarize_history_replaces_old_with_summary():
    client = FakeClient("did things to wordle.py")
    history = _history_with_old_turns()

    out = summarize_history(client, history, context_length=8192)

    assert out is not None
    assert out[0]["role"] == "system"
    assert out[1]["content"].startswith(SUMMARY_PREFIX)
    assert "did things to wordle.py" in out[1]["content"]
    # El tail reciente se conserva literal.
    assert out[-1]["content"] == history[-1]["content"]
    assert conservative_estimate(out) < conservative_estimate(history)


def test_summarize_history_tail_does_not_start_with_orphan_tool():
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(6):
        msgs.append({"role": "user", "content": f"req {i} " + "z" * 200})
    msgs.append(_assistant_call("c9", "bash"))
    msgs.append(_tool_msg("c9", "result"))
    msgs.append({"role": "assistant", "content": "done"})

    out = summarize_history(FakeClient(), msgs, context_length=8192)

    assert out is not None
    non_system = [m for m in out if m["role"] != "system"]
    # tras el resumen, el primer mensaje del tail nunca es un tool huérfano
    first_tool_idx = next(
        (i for i, m in enumerate(non_system) if m["role"] == "tool"), None
    )
    if first_tool_idx is not None:
        assert non_system[first_tool_idx - 1].get("tool_calls")


def test_summarize_history_returns_none_on_failure():
    history = _history_with_old_turns()
    assert summarize_history(FakeClient(fail=True), history, context_length=8192) is None


def test_summarize_history_returns_none_when_nothing_old():
    short = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hola"},
    ]
    assert summarize_history(FakeClient(), short, context_length=8192) is None


def test_summarize_history_rejects_tool_call_response():
    class ToolCallingClient(FakeClient):
        def chat(self, messages, *, tools=None):
            return FakeResponse("", tool_calls=[{"id": "x"}])

    history = _history_with_old_turns()
    assert summarize_history(ToolCallingClient(), history, context_length=8192) is None


# ---------- manage_context ----------

def test_manage_context_noop_below_threshold():
    history = [{"role": "user", "content": "hola"}]
    out, failures, events = manage_context(history, FakeClient(), 8192)
    assert out is history
    assert failures == 0
    assert events == []


def test_manage_context_micro_compact_first():
    msgs = [{"role": "system", "content": "sys"}]
    # Muchos resultados de tool enormes => micro-compact basta sin LLM.
    for i in range(20):
        msgs.append(_assistant_call(f"c{i}", "read_file"))
        msgs.append(_tool_msg(f"c{i}", "x" * 2000))

    client = FakeClient()
    out, failures, events = manage_context(msgs, client, context_length=16_384)

    assert failures == 0
    assert any("micro-compact" in e for e in events)
    # Si micro-compact bajó del umbral, no se llamó al LLM.
    assert client.calls == []
    stubbed = [m for m in out if m.get("content") == TOOL_RESULT_STUB]
    assert stubbed


def test_manage_context_falls_back_and_counts_failures():
    history = [{"role": "user", "content": "u" * 60_000}]
    for i in range(8):
        history.append({"role": "assistant", "content": f"a{i} " + "b" * 500})

    out, failures, events = manage_context(
        history, FakeClient(fail=True), context_length=4096
    )
    assert failures == 1
    assert any("falló" in e for e in events)
    # Historial intacto: el recorte lo hace trim_messages después.
    assert out[0]["content"] == history[0]["content"]


def test_manage_context_stops_retrying_after_max_failures():
    history = [{"role": "user", "content": "u" * 60_000}]
    client = FakeClient(fail=True)
    out, failures, events = manage_context(
        history, client, context_length=4096, summary_failures=3
    )
    assert failures == 3
    assert client.calls == []


def test_manage_context_summarizes_when_micro_compact_insufficient():
    history = [{"role": "system", "content": "sys"}]
    for i in range(12):
        history.append({"role": "user", "content": f"req {i} " + "u" * 800})
        history.append({"role": "assistant", "content": f"ans {i} " + "a" * 800})

    out, failures, events = manage_context(
        history, FakeClient("compact summary"), context_length=4096
    )
    assert failures == 0
    assert any("resumido" in e for e in events)
    assert any(
        isinstance(m.get("content"), str) and m["content"].startswith(SUMMARY_PREFIX)
        for m in out
    )
