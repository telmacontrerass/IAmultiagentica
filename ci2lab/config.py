"""
Centralized Ci2Lab configuration.

Priority (highest to lowest): CLI arguments > environment variables > ci2lab.yaml > defaults.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ci2lab.harness.security_profiles import (
    SecurityConfig,
    UnknownSecurityProfileError,
    parse_security_config,
)
from ci2lab.security.engine import UnknownSecurityEngineError
from ci2lab.security.opencode_presets import UnknownPermissionPresetError

DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_BACKEND = "ollama"
DEFAULT_BACKEND_URL = "http://localhost:11434/v1"
DEFAULT_TOOL_MODE = "native"
DEFAULT_MAX_ROUNDS = 25
DEFAULT_CONTEXT_LENGTH: int | None = None
DEFAULT_STREAM = True
DEFAULT_AUTO_CONFIRM = False
DEFAULT_RUNS_DIR = "runs"
DEFAULT_LOG_RUNS = True
DEFAULT_WRITE_TOOLS_ENABLED = True
DEFAULT_REQUIRE_DIFF_PREVIEW = True
# On by default at the product layer so a plain "user writes prompt -> problem
# solved" flow independently confirms the work before finishing, with no setting
# to enable. The mechanism is conservative (it only blocks on a confident,
# actionable failure and leans PASS otherwise). Set CI2LAB_VERIFY_COMPLETION=0
# (or verify_completion: false in ci2lab.yaml) to turn it off.
DEFAULT_VERIFY_COMPLETION = True
DEFAULT_VERIFY_FINAL_ANSWER = True

_CONFIG_FILENAMES = ("ci2lab.yaml", "ci2lab.yml", "ci2lab.json")


@dataclass
class Ci2LabConfig:
    model: str = DEFAULT_MODEL
    backend: str = DEFAULT_BACKEND
    """Inference provider that serves the model: ``ollama`` or ``openai`` (any
    OpenAI-compatible server such as vLLM, LM Studio or llama.cpp)."""
    backend_url: str = DEFAULT_BACKEND_URL
    tool_mode: str = DEFAULT_TOOL_MODE
    max_rounds: int = DEFAULT_MAX_ROUNDS
    context_length: int | None = DEFAULT_CONTEXT_LENGTH
    workspace: str | None = None
    stream: bool = DEFAULT_STREAM
    auto_confirm: bool = DEFAULT_AUTO_CONFIRM
    runs_dir: str = DEFAULT_RUNS_DIR
    log_runs: bool = DEFAULT_LOG_RUNS
    write_tools_enabled: bool = DEFAULT_WRITE_TOOLS_ENABLED
    require_diff_preview: bool = DEFAULT_REQUIRE_DIFF_PREVIEW
    verify_completion: bool = DEFAULT_VERIFY_COMPLETION
    verify_final_answer: bool = DEFAULT_VERIFY_FINAL_ANSWER
    security: SecurityConfig = field(default_factory=SecurityConfig)
    permission: dict[str, Any] = field(default_factory=dict)
    """OpenCode-style root-level permission (opencode_experimental only)."""


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_value(key: str, raw: str) -> Any:
    text = raw.strip().strip("'\"")
    if key in {"max_rounds", "context_length"}:
        return int(text)
    if key in {
        "stream",
        "auto_confirm",
        "log_runs",
        "write_tools_enabled",
        "require_diff_preview",
        "verify_completion",
        "verify_final_answer",
    }:
        return _parse_bool(text)
    if key == "no_log":
        return _parse_bool(text)
    return text


def _load_simple_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML parser (key: value pairs, no external dependencies)."""
    data: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        if not key or not value.strip():
            continue
        data[key] = _coerce_value(key, value)
    return data


def _load_file_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}
    return _load_simple_yaml(text)


def _find_config_file(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for name in _CONFIG_FILENAMES:
        candidate = Path.cwd() / name
        if candidate.is_file():
            return candidate
    home = Path.home() / ".ci2lab" / "ci2lab.yaml"
    if home.is_file():
        return home
    return None


def _normalize_backend_url(url: str) -> str:
    base = url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _apply_mapping(config: Ci2LabConfig, mapping: dict[str, Any]) -> Ci2LabConfig:
    alias = {
        "endpoint": "backend_url",
        "cwd": "workspace",
        "ollama_url": "backend_url",
    }
    valid = {f.name for f in fields(Ci2LabConfig)}
    updates: dict[str, Any] = {}
    for key, value in mapping.items():
        if value is None:
            continue
        if key == "no_log":
            if value:
                updates["log_runs"] = False
            continue
        if key == "security":
            if not isinstance(value, dict):
                raise ValueError("security must be a JSON/YAML object.")
            updates["security"] = parse_security_config(value)
            continue
        if key == "permission":
            if not isinstance(value, dict):
                raise ValueError("permission must be a JSON/YAML object.")
            updates["permission"] = dict(value)
            continue
        target = alias.get(key, key)
        if target == "backend_url" and isinstance(value, str):
            updates[target] = _normalize_backend_url(value)
        elif target in valid:
            updates[target] = value
    if not updates:
        return config
    return Ci2LabConfig(**{**config.__dict__, **updates})


def _from_env(config: Ci2LabConfig) -> Ci2LabConfig:
    mapping: dict[str, Any] = {}
    if model := os.environ.get("CI2LAB_MODEL"):
        mapping["model"] = model
    if backend := os.environ.get("CI2LAB_BACKEND"):
        mapping["backend"] = backend
    if url := os.environ.get("CI2LAB_OLLAMA_URL"):
        mapping["backend_url"] = url
    if backend := os.environ.get("CI2LAB_BACKEND_URL"):
        mapping["backend_url"] = backend
    if tool_mode := os.environ.get("CI2LAB_TOOL_MODE"):
        mapping["tool_mode"] = tool_mode
    if max_rounds := os.environ.get("CI2LAB_MAX_ROUNDS"):
        mapping["max_rounds"] = int(max_rounds)
    if workspace := os.environ.get("CI2LAB_WORKSPACE") or os.environ.get("CI2LAB_CWD"):
        mapping["workspace"] = workspace
    if stream := os.environ.get("CI2LAB_STREAM"):
        mapping["stream"] = _parse_bool(stream)
    if os.environ.get("CI2LAB_AUTO_CONFIRM", "").lower() in {"1", "true", "yes"}:
        mapping["auto_confirm"] = True
    if os.environ.get("CI2LAB_YES", "").lower() in {"1", "true", "yes"}:
        mapping["auto_confirm"] = True
    if runs_dir := os.environ.get("CI2LAB_RUNS_DIR"):
        mapping["runs_dir"] = runs_dir
    if os.environ.get("CI2LAB_NO_LOG", "").lower() in {"1", "true", "yes"}:
        mapping["log_runs"] = False
    if os.environ.get("CI2LAB_WRITE_TOOLS_ENABLED", "").lower() in {
        "0",
        "false",
        "no",
    }:
        mapping["write_tools_enabled"] = False
    if os.environ.get("CI2LAB_REQUIRE_DIFF_PREVIEW", "").lower() in {
        "0",
        "false",
        "no",
    }:
        mapping["require_diff_preview"] = False
    verify_completion_env = os.environ.get("CI2LAB_VERIFY_COMPLETION", "").lower()
    if verify_completion_env in {"1", "true", "yes", "on"}:
        mapping["verify_completion"] = True
    elif verify_completion_env in {"0", "false", "no", "off"}:
        mapping["verify_completion"] = False
    if os.environ.get("CI2LAB_VERIFY_FINAL_ANSWER", "").lower() in {"0", "false", "no"}:
        mapping["verify_final_answer"] = False
    return _apply_mapping(config, mapping)


def load_config(*, config_path: str | None = None) -> Ci2LabConfig:
    """
    Load defaults + ci2lab.yaml (if present) + environment variables.
    Does not include CLI overrides.
    """
    config = Ci2LabConfig()
    explicit = config_path or os.environ.get("CI2LAB_CONFIG")
    path = _find_config_file(explicit)
    if path:
        try:
            file_data = _load_file_config(path)
            config = _apply_mapping(config, file_data)
        except (
            UnknownSecurityProfileError,
            UnknownSecurityEngineError,
            UnknownPermissionPresetError,
        ):
            raise
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return _from_env(config)


def resolve_workspace(
    *,
    workspace: str | None,
    cwd: str | None,
    config: Ci2LabConfig,
) -> str:
    """Resolve the working directory; error if --workspace and --cwd coexist."""
    if workspace and cwd:
        raise ValueError("Use only one of --workspace or --cwd, not both.")
    raw = workspace or cwd or config.workspace
    if not raw:
        # Portable startup: when ci2lab is launched from its own repository,
        # allow an explicit workspace hint so models can be used "from anywhere".
        hinted = os.environ.get("CI2LAB_WORKSPACE_HINT", "").strip()
        if hinted and os.path.isdir(hinted):
            raw = hinted
    if not raw:
        raw = os.getcwd()
    return os.path.abspath(raw)


def merge_cli_config(
    base: Ci2LabConfig,
    *,
    model: str | None = None,
    backend: str | None = None,
    backend_url: str | None = None,
    tool_mode: str | None = None,
    max_rounds: int | None = None,
    context_length: int | None = None,
    workspace: str | None = None,
    cwd: str | None = None,
    stream: bool | None = None,
    no_stream: bool = False,
    auto_confirm: bool = False,
    runs_dir: str | None = None,
    no_log: bool = False,
) -> Ci2LabConfig:
    """Apply CLI overrides on top of the loaded config."""
    updates: dict[str, Any] = {}
    if model is not None:
        updates["model"] = model
    if backend is not None:
        updates["backend"] = backend
    if backend_url is not None:
        updates["backend_url"] = backend_url
    if tool_mode is not None:
        updates["tool_mode"] = tool_mode
    if max_rounds is not None:
        updates["max_rounds"] = max_rounds
    if context_length is not None:
        updates["context_length"] = context_length
    if stream is not None:
        updates["stream"] = stream
    elif no_stream:
        updates["stream"] = False
    if auto_confirm:
        updates["auto_confirm"] = True
    if runs_dir is not None:
        updates["runs_dir"] = runs_dir
    if no_log:
        updates["log_runs"] = False
    merged = _apply_mapping(base, updates)
    merged = Ci2LabConfig(
        **{
            **merged.__dict__,
            "workspace": resolve_workspace(
                workspace=workspace,
                cwd=cwd,
                config=merged,
            ),
        }
    )
    return merged
