"""Workspace hook lifecycle for harness runs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ci2lab.harness.types import AgentConfig

HOOK_EVENTS = frozenset({"before_tool", "after_tool", "after_final_answer"})
DEFAULT_HOOK_TIMEOUT_SECONDS = 5


def emit_hook_event(
    config: AgentConfig,
    event: str,
    payload: dict[str, Any],
) -> list[str]:
    """Run configured hook commands for an event and return non-fatal warnings.

    Args:
        config: Active harness configuration; supplies the workspace ``cwd`` used
            to locate and run hooks.
        event: Lifecycle event name. Must be one of :data:`HOOK_EVENTS`.
        payload: Event payload serialized to JSON and passed to each hook on
            stdin.

    Returns:
        Non-fatal warning messages collected while loading and running hooks. An
        empty list means every configured hook ran successfully.
    """
    if event not in HOOK_EVENTS:
        return [f"Unknown hook event: {event}"]
    hooks, warnings = _load_hooks(Path(config.cwd))
    for command in hooks.get(event, []):
        warnings.extend(_run_hook(command, config, event, payload))
    return warnings


def _load_hooks(cwd: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Load and validate the workspace ``hooks.json`` mapping events to commands.

    Args:
        cwd: Workspace root searched for ``.ci2lab/hooks.json``.

    Returns:
        A tuple of ``(hooks, warnings)`` where ``hooks`` maps each known event to
        its list of commands and ``warnings`` collects any validation messages.
    """
    path = cwd / ".ci2lab" / "hooks.json"
    if not path.is_file():
        return {}, []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Could not load hooks from {path}: {exc}"]

    source = raw.get("hooks", raw) if isinstance(raw, dict) else {}
    if not isinstance(source, dict):
        return {}, [f"Ignoring hooks from {path}: expected a JSON object."]

    hooks: dict[str, list[str]] = {}
    warnings: list[str] = []
    for event, entries in source.items():
        if event not in HOOK_EVENTS:
            warnings.append(f"Ignoring unknown hook event `{event}` in {path}.")
            continue
        commands = _normalize_commands(entries)
        if commands:
            hooks[event] = commands
    return hooks, warnings


def _normalize_commands(entries: Any) -> list[str]:
    """Coerce a raw hook entry into a flat list of command strings.

    Accepts a bare string, a list of strings, or a list of ``{"command": ...}``
    objects; anything else yields an empty list.
    """
    if isinstance(entries, str):
        return [entries]
    if not isinstance(entries, list):
        return []
    commands: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            commands.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("command"), str):
            commands.append(entry["command"])
    return commands


def _run_hook(
    command: str,
    config: AgentConfig,
    event: str,
    payload: dict[str, Any],
) -> list[str]:
    """Run a single hook command and return any non-fatal warning messages.

    The command runs through the shell with the JSON ``payload`` on stdin and
    ``CI2LAB_HOOK_EVENT`` set in the environment. A non-zero exit, timeout or OS
    error is reported as a warning rather than raised.

    Args:
        command: Shell command to execute.
        config: Active harness configuration; supplies the working directory.
        event: Lifecycle event name, exposed to the hook and used in messages.
        payload: Event payload serialized to JSON and passed on stdin.

    Returns:
        A list with a single warning string on failure, or an empty list on
        success.
    """
    env = os.environ.copy()
    env["CI2LAB_HOOK_EVENT"] = event
    try:
        completed = subprocess.run(
            command,
            cwd=config.cwd,
            input=json.dumps(payload, ensure_ascii=False, default=str),
            text=True,
            capture_output=True,
            timeout=DEFAULT_HOOK_TIMEOUT_SECONDS,
            shell=True,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"Hook `{command}` failed to run for {event}: {exc}"]
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if detail:
            detail = f": {detail[:300]}"
        return [f"Hook `{command}` exited {completed.returncode} for {event}{detail}"]
    return []
