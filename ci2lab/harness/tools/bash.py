"""Ejecución de comandos shell con timeout."""

from __future__ import annotations

import subprocess


def run_bash(cwd: str, command: str, timeout_seconds: int = 60) -> str:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return f"Error: comando superó el timeout de {timeout_seconds}s"
    except OSError as exc:
        return f"Error al ejecutar comando: {exc}"

    parts: list[str] = []
    if proc.stdout:
        parts.append(proc.stdout.rstrip())
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr.rstrip()}")
    if proc.returncode != 0:
        parts.append(f"[exit code {proc.returncode}]")
    return "\n".join(parts) if parts else f"(sin salida, exit {proc.returncode})"
