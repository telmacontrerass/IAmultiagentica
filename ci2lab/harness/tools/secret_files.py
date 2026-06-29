"""Policy for sensitive files within the workspace."""

from __future__ import annotations

import re
from pathlib import Path

#: Marker embedded in block messages so callers can detect a policy refusal.
POLICY_SECRET_FILE_BLOCKED: str = "POLICY_SECRET_FILE_BLOCKED"

#: Regex splitting a name stem into tokens on ``.``, ``_``, ``-`` and whitespace.
_TOKEN_SPLIT = re.compile(r"[._\-\s]+")

#: Single tokens whose presence marks a name as sensitive.
_SENSITIVE_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "token",
        "secret",
        "secrets",
        "password",
        "passwords",
        "credential",
        "credentials",
    }
)

#: Adjacent token pairs whose presence marks a name as sensitive.
_SENSITIVE_TOKEN_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("api", "key"),
        ("private", "key"),
    }
)

#: Exact (lowercased) file names treated as sensitive.
_SENSITIVE_EXACT_NAMES: frozenset[str] = frozenset({"id_rsa", "id_ed25519"})
#: File suffixes treated as sensitive (keys, certificates).
_SENSITIVE_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".pfx")


def secret_file_block_message() -> str:
    """Return the standard refusal message for blocked sensitive files.

    Returns:
        An ``"Error: ..."`` message embedding :data:`POLICY_SECRET_FILE_BLOCKED`.
    """
    return (
        f"Error: {POLICY_SECRET_FILE_BLOCKED}: cannot read sensitive files "
        "(secrets, credentials, keys, or tokens)."
    )


def _basename_stem(name: str) -> str:
    """Return the stem of ``name`` (dotfiles kept intact, else extension dropped)."""
    if name.startswith("."):
        return name
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _split_name_tokens(name: str) -> list[str]:
    """Split ``name``'s stem into lowercase, non-empty tokens."""
    stem = _basename_stem(name)
    return [part for part in _TOKEN_SPLIT.split(stem.lower()) if part]


def _tokens_are_sensitive(tokens: list[str]) -> bool:
    """True if any token, or adjacent token pair, is sensitive."""
    if any(token in _SENSITIVE_NAME_TOKENS for token in tokens):
        return True
    for idx in range(len(tokens) - 1):
        if (tokens[idx], tokens[idx + 1]) in _SENSITIVE_TOKEN_PAIRS:
            return True
    return False


def _is_sensitive_basename(name: str) -> bool:
    """Evaluate a path component (file or folder name)."""
    lower = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return True
    if (
        lower in _SENSITIVE_EXACT_NAMES
        or lower.startswith("id_rsa")
        or lower.startswith("id_ed25519")
    ):
        return True
    if any(lower.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True
    return _tokens_are_sensitive(_split_name_tokens(name))


def _sensitive_parts(path: Path, workspace: Path | str | None) -> list[str]:
    """Return the path components to evaluate for sensitivity.

    With a ``workspace``, returns the components relative to it (or the basename
    if ``path`` lies outside); without one, returns just the basename.
    """
    resolved = path.resolve()
    if workspace is not None:
        base = Path(workspace).resolve()
        try:
            return list(resolved.relative_to(base).parts)
        except ValueError:
            return [resolved.name]
    return [resolved.name]


def is_sensitive_path(path: Path, *, workspace: Path | str | None = None) -> bool:
    """Report whether the resolved path appears to contain secrets/credentials.

    Args:
        path: The path to evaluate (resolved internally).
        workspace: Optional workspace root. When passed, only components
            relative to the workspace are evaluated (avoids false positives from
            OS or test-runner folder names). Without it, only the target file's
            basename is evaluated.

    Returns:
        ``True`` if any evaluated path component looks sensitive.
    """
    return any(_is_sensitive_basename(part) for part in _sensitive_parts(path, workspace))


def grep_skip_notice(skipped: int) -> str:
    """Format a notice about sensitive files skipped during a search.

    Args:
        skipped: The number of sensitive files skipped.

    Returns:
        A parenthesised notice, or an empty string when nothing was skipped.
    """
    if skipped <= 0:
        return ""
    return f"(policy: skipped {skipped} sensitive file(s) from the search)"
