"""Offload oversized tool output to a file instead of blind truncation.

When a tool returns more than the per-call character budget, the old behavior
kept the head and threw the rest away — the model could never recover the tail.
Instead we write the full result to a file under the workspace and hand back a
head+tail preview plus a pointer, so the model can page through the rest with
`read_file` (offset/limit) if it actually needs it. The in-context message stays
small either way.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_OFFLOAD_DIR = Path(".ci2lab") / "tool_outputs"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _truncation_fallback(output: str, max_chars: int) -> str:
    return output[:max_chars] + f"\n... (truncated, {len(output)} characters total)"


def offload_large_output(
    cwd: str,
    tool_name: str,
    call_id: str | None,
    output: str,
    max_chars: int,
) -> str:
    """Return a compact preview, writing the full output to a workspace file.

    Falls back to plain truncation if the file cannot be written, so a failure
    here never breaks the tool call.
    """
    total = len(output)
    try:
        out_dir = Path(cwd) / _OFFLOAD_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = _SAFE_NAME_RE.sub("_", tool_name) or "tool"
        ident = call_id or hashlib.md5(output.encode("utf-8")).hexdigest()[:8]
        ident = _SAFE_NAME_RE.sub("_", str(ident))
        target = out_dir / f"{stem}_{ident}.txt"
        target.write_text(output, encoding="utf-8")
    except Exception:  # noqa: BLE001
        return _truncation_fallback(output, max_chars)

    # Path the model passes to read_file: relative to the workspace so it
    # resolves the same way every other tool path does.
    rel = (_OFFLOAD_DIR / target.name).as_posix()

    head_chars = max(0, int(max_chars * 0.6))
    tail_chars = max(0, int(max_chars * 0.3))
    head = output[:head_chars].rstrip()
    tail = output[-tail_chars:].lstrip() if tail_chars else ""

    return (
        f"[Large {tool_name} output: {total} characters — too long to show in full. "
        f"The complete result was saved to `{rel}`. Read it with `read_file` and "
        f"page through it with offset/limit if you need more than this preview.]\n\n"
        f"--- first {len(head)} characters ---\n{head}\n\n"
        f"--- last {len(tail)} characters ---\n{tail}"
    )
