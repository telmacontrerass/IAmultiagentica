"""Parsing for the scalar frontmatter used by skills and Yard manifests."""

from __future__ import annotations

import re

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse leading ``---`` delimited scalar metadata and return it with the body."""
    if not text.startswith("---"):
        return {}, text.strip()
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        normalized_key = key.strip().lower().replace("-", "_")
        normalized_value = value.strip().strip("'\"")
        if normalized_value:
            metadata[normalized_key] = normalized_value
    return metadata, text[match.end() :].strip()
