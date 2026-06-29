from ci2lab.harness.query.retry_governor import (
    error_class_key,
    normalize_error_class,
)
from ci2lab.harness.types import ToolCall, ToolResult


def _err(content: str, outcome: str | None = None) -> ToolResult:
    return ToolResult(tool_name="docx_to_pdf", content=content, is_error=True, outcome=outcome)


def test_normalize_error_class_maps_known_errors():
    assert normalize_error_class(_err("Error: a valid PDF engine is missing.")) == "no_pdf_engine"
    assert normalize_error_class(_err("Error: file does not exist: /x")) == "source_not_found"
    assert normalize_error_class(_err("Error: old_string not found in the file")) == "edit_mismatch"
    assert (
        normalize_error_class(_err("Error: 'x' is not a valid .docx (not an OOXML package)"))
        == "invalid_source"
    )
    assert normalize_error_class(_err("Error: path outside the workspace")) == "path_outside"


def test_normalize_error_class_prefers_outcome():
    r = _err(
        "tool `x` is not allowed by the active skill. Allowed: ls.", outcome="blocked_by_skill"
    )
    assert normalize_error_class(r) == "not_allowed_by_skill"
    r2 = _err("Error: blocked", outcome="blocked_by_policy")
    assert normalize_error_class(r2) == "blocked_by_policy"


def test_normalize_error_class_defaults():
    assert normalize_error_class(_err("Error: something unexpected")) == "tool_error"
    assert normalize_error_class(ToolResult(tool_name="ls", content="ok", is_error=False)) == "none"


def test_error_class_key_ignores_arguments():
    call_a = ToolCall(name="docx_to_pdf", arguments={"source": "a.docx", "output": "a.pdf"})
    call_b = ToolCall(name="docx_to_pdf", arguments={"source": "b.docx", "output": "b.pdf"})
    result = _err("Error: a valid PDF engine is missing.")
    # Same tool + same error class -> same coarse key regardless of args.
    assert error_class_key(call_a, result) == error_class_key(call_b, result)
    assert error_class_key(call_a, result) == "docx_to_pdf::no_pdf_engine"
