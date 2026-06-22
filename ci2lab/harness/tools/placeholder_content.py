"""Detect write_file content that is a bare placeholder, not real text.

Weaker models sometimes treat "read X and write it to a file" as a templating
task: they narrate "store the text in a variable" and then write the *variable
reference* (`${exercise_1_instructions}`, `<extracted_instructions>`) to the
file instead of the actual content they were asked to produce. There is no
templating layer, so the file ends up holding a useless token.

We reject only when the **entire** body is a single placeholder token — a real
template file (`.env`, CI config) has surrounding text, so it never trips this.
"""

from __future__ import annotations

import re

# Each pattern matches a whole-body placeholder. Anchored and single-token so
# legitimate one-liners with real text do not match.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^\$\{[^{}]*\}$"),       # ${exercise_1_instructions}
    re.compile(r"^\{\{[^{}]*\}\}$"),     # {{ extracted_instructions }}
    re.compile(r"^\$[A-Za-z_]\w*$"),     # $instructions
    re.compile(r"^<[^<>]*>$"),           # <extracted_instructions> / <insert ... here>
)


def looks_like_placeholder_content(content: str) -> bool:
    """True if the whole content is one placeholder/variable token."""
    text = (content or "").strip()
    if not text or "\n" in text:
        return False
    return any(pattern.match(text) for pattern in _PLACEHOLDER_PATTERNS)


def placeholder_content_message(content: str) -> str:
    token = (content or "").strip()
    return (
        f"Error: the content is a placeholder ({token!r}), not real text. There "
        "is no templating or variable substitution here — whatever you put in "
        "`content` is written to the file verbatim. Copy the ACTUAL text "
        "(e.g. the instructions you extracted from the document above) directly "
        "into the `content` argument and call write_file again."
    )
