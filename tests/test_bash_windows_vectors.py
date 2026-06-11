"""Tests de vectores bash adicionales en Windows."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ci2lab.harness.tools.bash_safety import check_bash_blocked


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inside.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("decoy", encoding="utf-8")
    return ws


@pytest.fixture
def outside_secret(tmp_path: Path) -> Path:
    return (tmp_path / "outside" / "secret.txt").resolve()


@pytest.mark.parametrize(
    "command",
    [
        "cmd /c type {outside}",
        'powershell -Command "Get-Content {outside}"',
        'Start-Process -FilePath "{outside}"',
        'iex (Get-Content "{outside}")',
        'Invoke-Expression (Get-Content "{outside}")',
    ],
)
def test_bash_windows_external_vectors_blocked(
    workspace: Path, outside_secret: Path, command: str
):
    cmd = command.format(outside=outside_secret)
    blocked = check_bash_blocked(cmd, cwd=str(workspace))
    assert blocked is not None


def test_bash_userprofile_expansion_blocked_outside(
    workspace: Path, outside_secret: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("USERPROFILE", str(outside_secret.parent.parent))
    outside = outside_secret.parent / "secret.txt"
    cmd = f"type %USERPROFILE%\\outside\\secret.txt"
    blocked = check_bash_blocked(cmd, cwd=str(workspace))
    assert blocked is not None


def test_bash_dollar_env_userprofile_blocked(
    workspace: Path, outside_secret: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("USERPROFILE", str(outside_secret.parent.parent))
    cmd = f'Get-Content "$env:USERPROFILE\\outside\\secret.txt"'
    blocked = check_bash_blocked(cmd, cwd=str(workspace))
    assert blocked is not None


def test_bash_unc_path_blocked(workspace: Path):
    blocked = check_bash_blocked(
        r"type \\server\share\secret.txt",
        cwd=str(workspace),
    )
    assert blocked is not None


def test_bash_blocks_invoke_expression_even_inside_workspace(workspace: Path):
    blocked = check_bash_blocked("Invoke-Expression 'Write-Host hi'", cwd=str(workspace))
    assert blocked is not None


def test_bash_blocks_iex_even_inside_workspace(workspace: Path):
    blocked = check_bash_blocked("iex '1+1'", cwd=str(workspace))
    assert blocked is not None


@pytest.mark.skip(
    reason="Start-Process sin ruta externa explicita no se bloquea; "
    "solo se valida acceso fuera del workspace cuando hay path."
)
def test_start_process_without_path_not_blocked(workspace: Path):
    assert check_bash_blocked("Start-Process notepad", cwd=str(workspace)) is None
