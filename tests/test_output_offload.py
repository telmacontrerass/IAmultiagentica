"""Tests for large-tool-output offload and superseded-read pruning."""

from pathlib import Path

from ci2lab.harness.context.compact import (
    SUPERSEDED_READ_STUB,
    prune_superseded_reads,
)
from ci2lab.harness.tools.output_offload import offload_large_output


def test_offload_writes_full_output_and_returns_preview(tmp_path):
    output = "HEADSTART" + ("x" * 5000) + "TAILEND"
    preview = offload_large_output(str(tmp_path), "read_file", "c1", output, 1000)

    # Full content is saved to disk and recoverable.
    saved = tmp_path / ".ci2lab" / "tool_outputs" / "read_file_c1.txt"
    assert saved.is_file()
    assert saved.read_text(encoding="utf-8") == output

    # Preview is small, names the path, and shows both ends.
    assert len(preview) < len(output)
    assert ".ci2lab/tool_outputs/read_file_c1.txt" in preview
    assert "HEADSTART" in preview
    assert "TAILEND" in preview
    assert str(len(output)) in preview  # total char count surfaced


def test_offload_falls_back_to_truncation_when_unwritable(tmp_path):
    # Point cwd at a file so mkdir/write fails; we must still degrade gracefully.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    out = offload_large_output(str(blocker), "bash", "c9", "y" * 3000, 500)
    assert "characters total" in out  # plain truncation fallback
    assert len(out) < 3000


def _assistant_read(call_id, path):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": call_id,
            "function": {"name": "read_file", "arguments": f'{{"path": "{path}"}}'},
        }],
    }


def _tool_result(call_id, content):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_superseded_read_is_pruned_keeping_latest():
    big = "A" * 400  # over MIN_STUB_CHARS so it is eligible
    newer = "B" * 400
    messages = [
        {"role": "user", "content": "edit main.py"},
        _assistant_read("c1", "main.py"),
        _tool_result("c1", big),
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "w1", "function": {"name": "write_file", "arguments": '{"path": "main.py", "content": "x"}'}}
        ]},
        _tool_result("w1", "Wrote main.py"),
        _assistant_read("c2", "main.py"),
        _tool_result("c2", newer),
    ]
    pruned, count = prune_superseded_reads(messages)

    assert count == 1
    # Older read stubbed, newer read intact.
    assert pruned[2]["content"] == SUPERSEDED_READ_STUB.format(path="main.py")
    assert pruned[6]["content"] == newer


def test_distinct_paths_are_not_pruned():
    messages = [
        _assistant_read("c1", "a.py"),
        _tool_result("c1", "A" * 400),
        _assistant_read("c2", "b.py"),
        _tool_result("c2", "B" * 400),
    ]
    pruned, count = prune_superseded_reads(messages)
    assert count == 0
    assert pruned[1]["content"] == "A" * 400
    assert pruned[3]["content"] == "B" * 400
