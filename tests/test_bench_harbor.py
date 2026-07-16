"""Tests for the Terminal-Bench (Harbor) glue helpers and the ``--version`` flag.

The ``harbor``-importing shim (``benchmarks/harbor/ci2lab_harbor.py``) is not
imported here: it requires the external Harbor package. Everything it relies on
lives in ``ci2lab.bench.harbor`` and is exercised directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ci2lab.bench.harbor import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MODEL,
    TokenReadback,
    agent_env,
    build_install_command,
    build_run_command,
    find_latest_run_summary,
    read_run_summary,
)
from ci2lab.config import DEFAULT_MAX_ROUNDS as PRODUCT_MAX_ROUNDS


def test_build_run_command_single_agent() -> None:
    cmd = build_run_command("find the bug")
    # Invoked as a module, not the bare console script, so it does not depend on
    # pip's script dir being on PATH inside an arbitrary task image (exit 127).
    assert cmd.startswith("python3 -m ci2lab.cli agent ")
    assert "--multi-agent" not in cmd
    assert "--yes" in cmd
    assert "--no-stream" in cmd
    # No --workspace by default: ci2lab falls back to the process cwd, which
    # Harbor sets to each task's own workdir (datasets differ: /app vs /workdir).
    assert "--workspace" not in cmd
    assert "--runs-dir" in cmd
    assert "'find the bug'" in cmd
    assert "tee" in cmd


def test_build_run_command_omits_workspace_unless_overridden() -> None:
    # A hardcoded workdir broke every task built on a non-/app root; the default
    # must delegate to the task workdir, while an explicit override still works.
    assert "--workspace" not in build_run_command("x")
    assert "--workspace /workdir" in build_run_command("x", workdir="/workdir")


def test_build_run_command_multi_agent_flag_precedes_subcommand() -> None:
    # --multi-agent is a global flag and must come BEFORE the agent subcommand.
    cmd = build_run_command("do it", multi=True)
    assert "python3 -m ci2lab.cli --multi-agent agent " in cmd


def test_build_run_command_quotes_untrusted_instruction() -> None:
    # An adversarial task prompt must stay a single shell-quoted argument.
    cmd = build_run_command("go; rm -rf / #pwn")
    assert "'go; rm -rf / #pwn'" in cmd


def test_build_run_command_honors_workdir_and_engine() -> None:
    cmd = build_run_command("x", workdir="/task", security_engine="claude_experimental")
    assert "--workspace /task" in cmd
    assert "--security-engine claude_experimental" in cmd


def test_agent_env_defaults() -> None:
    env = agent_env()
    assert env["CI2LAB_MODEL"] == DEFAULT_MODEL
    assert env["CI2LAB_BACKEND_URL"].endswith(":11434/v1")
    assert env["CI2LAB_NUM_CTX"].isdigit()
    assert env["CI2LAB_REQUIRE_DIFF_PREVIEW"] == "0"


def test_agent_env_overrides() -> None:
    env = agent_env(model="devstral:24b", backend_url="http://x:1/v1", num_ctx=8192)
    assert env["CI2LAB_MODEL"] == "devstral:24b"
    assert env["CI2LAB_BACKEND_URL"] == "http://x:1/v1"
    assert env["CI2LAB_NUM_CTX"] == "8192"


def test_agent_env_raises_the_round_cap_above_the_product_default() -> None:
    # A benchmark trial must be stopped by the task's wall-clock timeout (applied
    # identically to every arm), not by ci2lab's interactive 25-round default —
    # otherwise the score measures the round budget instead of the harness.
    env = agent_env()
    assert int(env["CI2LAB_MAX_ROUNDS"]) == DEFAULT_MAX_ROUNDS
    assert int(env["CI2LAB_MAX_ROUNDS"]) > PRODUCT_MAX_ROUNDS
    assert agent_env(max_rounds=7)["CI2LAB_MAX_ROUNDS"] == "7"


def test_install_command_falls_back_when_break_system_packages_unsupported() -> None:
    # pip < 23 has no --break-system-packages and exits 2 on it; PEP-668 images
    # need it. Neither form works everywhere, so both must be attempted.
    cmd = build_install_command("http://h:8000/x.whl")
    guarded, _, fallback = cmd.partition("||")
    assert "--break-system-packages" in guarded
    assert "--break-system-packages" not in fallback
    assert "pip install" in fallback
    assert "http://h:8000/x.whl" in guarded and "http://h:8000/x.whl" in fallback


def _write_run_summary(
    dirpath: Path,
    *,
    prompt: int,
    completion: int,
    total: int,
    rounds: int,
    status: str,
    mtime: float,
) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    summary = dirpath / "run_summary.json"
    summary.write_text(
        json.dumps(
            {
                "status": status,
                "rounds": rounds,
                "token_usage": {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                },
            }
        ),
        encoding="utf-8",
    )
    os.utime(summary, (mtime, mtime))


def test_read_run_summary_parses_tokens(tmp_path: Path) -> None:
    _write_run_summary(
        tmp_path / "runs" / "2026_aaa",
        prompt=100,
        completion=40,
        total=140,
        rounds=5,
        status="success",
        mtime=1000.0,
    )
    assert read_run_summary(tmp_path) == TokenReadback(
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        rounds=5,
        status="success",
    )


def test_read_run_summary_missing_returns_none(tmp_path: Path) -> None:
    assert read_run_summary(tmp_path) is None
    assert find_latest_run_summary(tmp_path) is None


def test_read_run_summary_picks_newest(tmp_path: Path) -> None:
    _write_run_summary(
        tmp_path / "old",
        prompt=1,
        completion=1,
        total=2,
        rounds=1,
        status="success",
        mtime=1000.0,
    )
    _write_run_summary(
        tmp_path / "new",
        prompt=9,
        completion=9,
        total=18,
        rounds=9,
        status="max_rounds",
        mtime=2000.0,
    )
    latest = find_latest_run_summary(tmp_path)
    assert latest is not None
    assert latest.parent.name == "new"
    got = read_run_summary(tmp_path)
    assert got is not None
    assert got.total_tokens == 18
    assert got.status == "max_rounds"


def test_read_run_summary_tolerates_malformed_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "broken"
    run_dir.mkdir()
    (run_dir / "run_summary.json").write_text("{not json", encoding="utf-8")
    assert read_run_summary(tmp_path) is None


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    from ci2lab import __version__
    from ci2lab.cli import main

    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out
