"""Run the documented CI2Lab v0.1 regression gate."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


GATE_NAME = "CI2Lab v0.1 Regression Gate"

AREAS: list[tuple[str, list[str]]] = [
    ("CLI", [
        "tests/test_cli_help.py",
        "tests/test_cli_doctor.py",
        "tests/test_multiagent_cli.py",
    ]),
    ("Loop clasico", [
        "tests/test_harness_loop.py",
        "tests/test_pipeline.py",
    ]),
    ("Herramientas de archivo", [
        "tests/test_harness_tools.py",
    ]),
    ("Escritura supervisada", [
        "tests/test_write_preview.py",
        "tests/test_write_file_intent_policy.py",
        "tests/test_apply_patch.py",
    ]),
    ("Seguridad workspace", [
        "tests/test_workspace_security.py",
        "tests/test_security_core.py",
    ]),
    ("Secretos", [
        "tests/test_secret_files_policy.py",
        "tests/test_secret_files_v02.py",
    ]),
    ("Bash safety", [
        "tests/test_bash_safety.py",
        "tests/test_bash_redirect.py",
        "tests/test_bash_windows_vectors.py",
    ]),
    ("Permisos", [
        "tests/test_security_engine.py",
        "tests/test_security_profiles.py",
        "tests/test_session_permissions.py",
    ]),
    ("Run logging", [
        "tests/test_run_logger.py",
    ]),
    ("Multiagente intent", [
        "tests/test_multiagent_intent.py",
    ]),
    ("Multiagente runner/orchestrator", [
        "tests/test_multiagent_runner.py",
        "tests/test_multiagent_orchestrator.py",
    ]),
    ("Multiagente tooling/validacion", [
        "tests/test_multiagent_tooling.py",
    ]),
    ("Evals/redteam", [
        "tests/test_evals.py",
        "tests/redteam/test_redteam_findings.py",
    ]),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _test_files() -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for _, area_files in AREAS:
        for path in area_files:
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _build_pytest_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, "-m", "pytest"]
    if args.collect_only:
        command.extend(["--collect-only", "-q"])
    elif args.quiet:
        command.append("-q")
    command.extend(_test_files())
    return command


def _print_command(command: list[str]) -> None:
    print("Pytest command:")
    print(" ".join(command))


def _print_summary(command: list[str]) -> None:
    files = _test_files()
    print(GATE_NAME)
    print(f"Test files: {len(files)}")
    print("Areas covered:")
    for area, area_files in AREAS:
        print(f"- {area}: {', '.join(area_files)}")
    print()
    _print_command(command)
    print()


def _list_gate() -> int:
    print(GATE_NAME)
    print(f"Test files: {len(_test_files())}")
    print()
    for area, area_files in AREAS:
        print(area)
        for path in area_files:
            print(f"  - {path}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the CI2Lab v0.1 regression gate.",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Collect the documented tests without running them.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Pass -q to pytest.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List areas and tests without running pytest.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    root = _repo_root()
    if args.list:
        return _list_gate()

    tmp = root / ".pytest-tmp"
    tmp.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = str(tmp)
    env["TMP"] = str(tmp)

    command = _build_pytest_command(args)
    _print_summary(command)
    sys.stdout.flush()
    completed = subprocess.run(command, cwd=root, env=env)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
