"""Fetch remote web content (read-only)."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

import httpx

_DEFAULT_MAX_CHARS = 80_000
_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "ci2lab/0.1 (local coding agent)"


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def web_fetch(url: str, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    if not url or not str(url).strip():
        return "Error: url is required"

    raw_url = str(url).strip()
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return "Error: only http and https URLs are allowed"
    if not parsed.netloc:
        return f"Error: invalid URL {raw_url!r}"

    limit = max(1_000, min(int(max_chars), _DEFAULT_MAX_CHARS))

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = client.get(raw_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            body = response.text
    except httpx.HTTPStatusError as exc:
        return f"Error: HTTP {exc.response.status_code} for {raw_url}"
    except httpx.RequestError as exc:
        return f"Error: request failed for {raw_url}: {exc}"

    if "html" in content_type:
        body = _strip_html(body)

    total_len = len(body)
    if total_len > limit:
        body = body[:limit] + f"\n... (truncated, {total_len} characters total)"

    title = f"Fetched {raw_url} [{response.status_code}]"
    if content_type:
        title += f" ({content_type.split(';')[0]})"
    return f"{title}\n\n{body}"
