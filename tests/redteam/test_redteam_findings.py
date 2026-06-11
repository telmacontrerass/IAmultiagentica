"""PoC de hallazgos red team — xfail hasta fix."""

from __future__ import annotations

import pytest

from ci2lab.harness.parsing import resolve_tool_calls


def test_unknown_fenced_tag_must_not_execute_as_bash():
    calls = resolve_tool_calls("```unknown_tool\nx\n```", [], tool_mode="fenced")
    assert calls == []


@pytest.mark.xfail(
    reason="is_sensitive_path marca 'token' como substring en nombres legitimos",
    strict=True,
)
def test_secret_name_false_positive_token_in_filename(tmp_path):
    """Documenta RISK: nombres con 'token' se marcan sensibles."""
    from ci2lab.harness.tools.inspection import file_info

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "normal_tokenized_name.txt").write_text("ok\n", encoding="utf-8")
    out = file_info(str(ws), "normal_tokenized_name.txt")
    assert "sensitive: no" in out
