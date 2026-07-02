"""Tests for the Yard component registry, runner and gateway tool."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from ci2lab.cli.commands.yard import _cmd_yard
from ci2lab.config import Ci2LabConfig
from ci2lab.harness.tools.registry import execute_tool, get_function_schemas
from ci2lab.harness.tools.schemas_parts.registry import TOOL_NAMES
from ci2lab.harness.types import AgentConfig, ToolCall
from ci2lab.harness.yard import runner
from ci2lab.harness.yard.loader import (
    format_yard_catalog,
    get_component,
    load_components,
)

BUILTIN_COMPONENTS = {
    "boolean_coercion",
    "geo_toolkit",
    "window_layout",
    "llm_enricher",
    "places_client",
    "facade_estimator",
}


# --------------------------------------------------------------------------- #
# Registry / loader                                                           #
# --------------------------------------------------------------------------- #
def test_builtin_components_load() -> None:
    components = load_components(".")
    assert set(components) >= BUILTIN_COMPONENTS


def test_component_has_entrypoints_and_core_dir() -> None:
    components = load_components(".")
    geo = components["geo_toolkit"]
    assert geo.core_dir.is_dir()
    functions = {ep.function for ep in geo.entrypoints}
    assert "calcular_distancia_haversine" in functions
    assert geo.requires == ["requests"]


def test_workspace_component_overrides_builtin(tmp_path: Path) -> None:
    comp_dir = tmp_path / ".ci2lab" / "yard" / "custom" / "core"
    comp_dir.mkdir(parents=True)
    comp_dir.joinpath("mymod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (comp_dir.parent / "COMPONENT.md").write_text(
        """---
name: custom
title: Custom adder
description: Adds two numbers
kind: utility
---

```json
{
  "entrypoints": [
    {
      "function": "add",
      "module": "mymod",
      "ready": "pure",
      "summary": "Add two numbers.",
      "parameters": {"type": "object", "properties": {"a": {}, "b": {}}, "required": ["a", "b"]}
    }
  ]
}
```

# Custom adder
""",
        encoding="utf-8",
    )
    components = load_components(str(tmp_path))
    assert "custom" in components
    assert set(components) >= BUILTIN_COMPONENTS


def test_catalog_query_filter() -> None:
    components = load_components(".")
    filtered = format_yard_catalog(components, query="geo")
    assert "geo_toolkit" in filtered
    assert "boolean_coercion" not in filtered


def test_catalog_respects_char_budget() -> None:
    components = load_components(".")
    catalog = format_yard_catalog(components, budget_chars=120)
    assert len(catalog) <= 140  # budget + the truncation marker
    assert "catalog truncated" in catalog


# --------------------------------------------------------------------------- #
# Runner — real execution of pure entrypoints                                 #
# --------------------------------------------------------------------------- #
def _run(
    component_name: str,
    function: str,
    args: dict,
    *,
    config: AgentConfig | None = None,
    cwd: str = ".",
) -> dict:
    cfg = config or AgentConfig(cwd=cwd)
    components = load_components(cfg.cwd)
    component = get_component(components, component_name)
    assert component is not None
    entrypoint = component.entrypoint(function)
    assert entrypoint is not None
    core_dirs = [c.core_dir for c in components.values()]
    return runner.execute(component, entrypoint, args, core_dirs, config=cfg)


def _write_side_effect_component(tmp_path: Path, *, returns: str = '"done"') -> None:
    """Write a harmless workspace component with a ``side_effect`` entrypoint.

    Lets the confirmation gating be exercised without running one of the real
    host-mutating built-ins (which would open browser windows).
    """
    core = tmp_path / ".ci2lab" / "yard" / "toucher" / "core"
    core.mkdir(parents=True)
    core.joinpath("toucher.py").write_text(
        f"def touch():\n    return {returns}\n", encoding="utf-8"
    )
    (core.parent / "COMPONENT.md").write_text(
        """---
name: toucher
title: Toucher
description: Harmless host-effect stub for tests
kind: utility
---

```json
{
  "entrypoints": [
    {
      "function": "touch",
      "module": "toucher",
      "ready": "side_effect",
      "summary": "noop host effect",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  ]
}
```

# Toucher
""",
        encoding="utf-8",
    )


def test_run_pure_boolean_coercion() -> None:
    assert _run("boolean_coercion", "_a_bool", {"valor": "Sí"})["result"] is True
    assert _run("boolean_coercion", "_a_bool", {"valor": "no"})["result"] is False
    # Tri-state: an uninterpretable value yields None, not False.
    assert _run("boolean_coercion", "_a_bool", {"valor": "quizá"})["result"] is None


def test_run_pure_haversine() -> None:
    out = _run(
        "geo_toolkit",
        "calcular_distancia_haversine",
        {"lat1": 40.4168, "lon1": -3.7038, "lat2": 41.3874, "lon2": 2.1686},
    )
    assert out["ok"] is True
    assert 490_000 < out["result"] < 520_000


def test_run_cross_component_import_resolves() -> None:
    # places_client imports the sibling geo_toolkit module (`geometria`);
    # es_centro_comercial is pure and exercises the shared sys.path wiring.
    out = _run("places_client", "es_centro_comercial", {"direccion": "C.C. La Vaguada"})
    assert out["ok"] is True
    assert out["result"] is True


# --------------------------------------------------------------------------- #
# Runner — gating                                                             #
# --------------------------------------------------------------------------- #
def test_needs_key_entrypoint_is_gated_without_key() -> None:
    out = _run(
        "geo_toolkit",
        "calcular_distancia_andando",
        {"origen": "40.4,-3.7", "destino": "40.5,-3.6"},
    )
    assert out["ok"] is False
    assert out["status"] == "needs_key"
    assert "api_key" in out["missing"]


def test_needs_config_entrypoint_never_executes() -> None:
    out = _run(
        "llm_enricher",
        "promover_tier4",
        {"negocios_t4": [], "openai_api_key": "x"},
    )
    assert out["ok"] is False
    assert out["status"] == "needs_config"


def test_side_effect_entrypoint_requires_confirm() -> None:
    # Default config: not auto-confirmed and no confirm callback → declined.
    out = _run("window_layout", "abrir_layout", {"puerto": 8501})
    assert out["ok"] is False
    assert out["status"] == "needs_confirm"


def test_side_effect_blocked_when_write_tools_disabled() -> None:
    out = _run(
        "window_layout",
        "abrir_layout",
        {"puerto": 8501},
        config=AgentConfig(cwd=".", write_tools_enabled=False),
    )
    assert out["ok"] is False
    assert out["status"] == "blocked_read_only"


def test_side_effect_runs_when_auto_confirmed(tmp_path: Path) -> None:
    _write_side_effect_component(tmp_path)
    out = _run(
        "toucher",
        "touch",
        {},
        config=AgentConfig(cwd=str(tmp_path), auto_confirm=True),
    )
    assert out["ok"] is True
    assert out["result"] == "done"


def test_side_effect_routes_through_confirm_callback(tmp_path: Path) -> None:
    _write_side_effect_component(tmp_path)
    consulted: list[str] = []

    def deny(tool: str, detail: str) -> bool:
        consulted.append(tool)
        return False

    out = _run(
        "toucher",
        "touch",
        {},
        config=AgentConfig(cwd=str(tmp_path), confirm_callback=deny),
    )
    assert out["ok"] is False
    assert out["status"] == "needs_confirm"
    assert consulted and consulted[0].startswith("yard/")

    out_ok = _run(
        "toucher",
        "touch",
        {},
        config=AgentConfig(cwd=str(tmp_path), confirm_callback=lambda *_: True),
    )
    assert out_ok["ok"] is True


def test_large_result_is_not_truncated_by_runner(tmp_path: Path) -> None:
    # The runner returns the whole value; the executor's central offload path
    # (max_tool_output_chars) is what previews oversized output, not the runner.
    _write_side_effect_component(tmp_path, returns='"X" * 50000')
    out = _run(
        "toucher",
        "touch",
        {},
        config=AgentConfig(cwd=str(tmp_path), auto_confirm=True),
    )
    assert out["ok"] is True
    assert out["status"] == "ok"
    assert len(out["result"]) == 50_000


def test_missing_required_param_is_reported() -> None:
    out = _run("boolean_coercion", "_normalizar", {})
    assert out["ok"] is False
    assert out["status"] == "missing_params"
    assert "texto" in out["missing"]


# --------------------------------------------------------------------------- #
# Runner — security-profile + workspace-confinement threading                 #
# --------------------------------------------------------------------------- #
def test_side_effect_blocked_by_strict_profile() -> None:
    # Under strict/audit (which disable bash/write_file), host-mutating
    # entrypoints are refused before any confirmation — even auto-confirmed.
    out = _run(
        "window_layout",
        "abrir_layout",
        {"puerto": 8501},
        config=AgentConfig(cwd=".", security_profile="strict", auto_confirm=True),
    )
    assert out["ok"] is False
    assert out["status"] == "blocked_by_security_profile"


def test_path_param_escaping_workspace_is_blocked(tmp_path: Path) -> None:
    # facade_estimator._encode_image declares `ruta` as a path param, so a path
    # that escapes the workspace is refused like the read/write file tools.
    out = _run(
        "facade_estimator",
        "_encode_image",
        {"ruta": "../../etc/passwd"},
        config=AgentConfig(cwd=str(tmp_path)),
    )
    assert out["ok"] is False
    assert out["status"] == "blocked_by_workspace"


def test_path_param_within_workspace_is_allowed(tmp_path: Path) -> None:
    img = tmp_path / "img.bin"
    img.write_bytes(b"hello-bytes")
    out = _run(
        "facade_estimator",
        "_encode_image",
        {"ruta": str(img)},
        config=AgentConfig(cwd=str(tmp_path)),
    )
    assert out["ok"] is True
    # base64("hello-bytes") — confinement passed and the real function ran.
    assert out["result"] == "aGVsbG8tYnl0ZXM="


# --------------------------------------------------------------------------- #
# Gateway tool + registry wiring                                              #
# --------------------------------------------------------------------------- #
def test_yard_is_a_single_registered_tool() -> None:
    assert "yard" in TOOL_NAMES
    schema_names = {s["function"]["name"] for s in get_function_schemas()}
    assert "yard" in schema_names
    # The catalog must NOT balloon the per-turn schema: one tool, not six.
    assert not (BUILTIN_COMPONENTS & schema_names)


def test_yard_tool_list_action() -> None:
    result = execute_tool(
        ToolCall(name="yard", arguments={"action": "list"}),
        AgentConfig(cwd="."),
    )
    assert not result.is_error
    assert "geo_toolkit" in result.content
    assert "boolean_coercion" in result.content


def test_yard_tool_describe_action() -> None:
    result = execute_tool(
        ToolCall(name="yard", arguments={"action": "describe", "component": "geo_toolkit"}),
        AgentConfig(cwd="."),
    )
    assert not result.is_error
    assert "calcular_distancia_haversine" in result.content
    assert "Porting guide" in result.content


def test_yard_tool_run_action_executes() -> None:
    result = execute_tool(
        ToolCall(
            name="yard",
            arguments={
                "action": "run",
                "component": "boolean_coercion",
                "entrypoint": "_a_bool",
                "args": {"valor": 1},
            },
        ),
        AgentConfig(cwd="."),
    )
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"] is True


def test_yard_tool_large_run_result_is_offloaded(tmp_path: Path) -> None:
    # gap #2 end-to-end: a large run result rides the executor's central offload
    # (preview in context, full result on disk) instead of being dropped.
    _write_side_effect_component(tmp_path, returns='"Y" * 40000')
    result = execute_tool(
        ToolCall(
            name="yard",
            arguments={
                "action": "run",
                "component": "toucher",
                "entrypoint": "touch",
                "args": {},
            },
        ),
        AgentConfig(cwd=str(tmp_path), auto_confirm=True, max_tool_output_chars=2000),
    )
    assert not result.is_error
    assert "Large yard output" in result.content
    assert len(result.content) < 40_000
    assert (tmp_path / ".ci2lab" / "tool_outputs").is_dir()


def test_yard_tool_unknown_component_errors_gracefully() -> None:
    result = execute_tool(
        ToolCall(name="yard", arguments={"action": "describe", "component": "nope"}),
        AgentConfig(cwd="."),
    )
    assert "unknown component" in result.content.lower()


def test_yard_tool_ambiguous_entrypoint_prompts_for_one() -> None:
    result = execute_tool(
        ToolCall(name="yard", arguments={"action": "run", "component": "geo_toolkit"}),
        AgentConfig(cwd="."),
    )
    # geo_toolkit exposes several entrypoints; run must ask which one.
    assert "entrypoint" in result.content.lower()


@pytest.mark.parametrize("action", ["", "bogus"])
def test_yard_tool_rejects_bad_action(action: str) -> None:
    result = execute_tool(
        ToolCall(name="yard", arguments={"action": action}),
        AgentConfig(cwd="."),
    )
    assert "unknown action" in result.content.lower()


# --------------------------------------------------------------------------- #
# CLI command (`ci2lab yard`) — parity with `ci2lab skills`                    #
# --------------------------------------------------------------------------- #
def _cli(namespace: SimpleNamespace, tmp_path: Path, monkeypatch) -> tuple[int, str]:
    """Run ``_cmd_yard`` with a captured console, returning (exit_code, output)."""
    out = tmp_path / "yard_cli.txt"
    with out.open("w", encoding="utf-8") as handle:
        monkeypatch.setattr(
            "ci2lab.cli.commands.yard.console",
            Console(file=handle, width=200),
        )
        code = _cmd_yard(namespace, Ci2LabConfig(workspace="."))
    return code, out.read_text(encoding="utf-8")


def test_cmd_yard_list(tmp_path: Path, monkeypatch) -> None:
    code, text = _cli(
        SimpleNamespace(yard_command="list", query=[], json=False, workspace="."),
        tmp_path,
        monkeypatch,
    )
    assert code == 0
    assert "geo_toolkit" in text
    assert "boolean_coercion" in text


def test_cmd_yard_list_query_filters(tmp_path: Path, monkeypatch) -> None:
    code, text = _cli(
        SimpleNamespace(yard_command="list", query=["geo"], json=False, workspace="."),
        tmp_path,
        monkeypatch,
    )
    assert code == 0
    assert "geo_toolkit" in text
    assert "boolean_coercion" not in text


def test_cmd_yard_describe(tmp_path: Path, monkeypatch) -> None:
    code, text = _cli(
        SimpleNamespace(yard_command="describe", component="geo_toolkit", workspace="."),
        tmp_path,
        monkeypatch,
    )
    assert code == 0
    assert "calcular_distancia_haversine" in text


def test_cmd_yard_run_pure(tmp_path: Path, monkeypatch) -> None:
    code, text = _cli(
        SimpleNamespace(
            yard_command="run",
            component="boolean_coercion",
            entrypoint="_a_bool",
            args='{"valor": 1}',
            yes=False,
            workspace=".",
        ),
        tmp_path,
        monkeypatch,
    )
    assert code == 0
    assert '"result": true' in text.lower() or '"result":true' in text.lower()


def test_cmd_yard_run_side_effect_declined_without_yes(tmp_path: Path, monkeypatch) -> None:
    code, text = _cli(
        SimpleNamespace(
            yard_command="run",
            component="window_layout",
            entrypoint="abrir_layout",
            args='{"puerto": 8501}',
            yes=False,
            workspace=".",
        ),
        tmp_path,
        monkeypatch,
    )
    # Declined (no auto-confirm) → non-zero exit, and the host effect never ran.
    assert code == 1
    assert "needs_confirm" in text
