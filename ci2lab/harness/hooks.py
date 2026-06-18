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
    """Run configured hook commands for an event and return non-fatal warnings."""
    if event not in HOOK_EVENTS:
        return [f"Unknown hook event: {event}"]
    hooks, warnings = _load_hooks(Path(config.cwd))
    for command in hooks.get(event, []):
        warnings.extend(_run_hook(command, config, event, payload))
    return warnings


def _load_hooks(cwd: Path) -> tuple[dict[str, list[str]], list[str]]:
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
