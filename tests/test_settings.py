"""Tests para ci2lab/settings.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci2lab.settings import (
    ToolSettings,
    _merge,
    check_tool_allowed,
    load_settings,
    subject_for_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# subject_for_tool
# ---------------------------------------------------------------------------

class TestSubjectForTool:
    def test_bash_returns_command(self):
        assert subject_for_tool("bash", {"command": "rm -rf ."}) == "rm -rf ."

    def test_web_fetch_returns_url(self):
        assert subject_for_tool("web_fetch", {"url": "https://example.com"}) == "https://example.com"

    def test_path_tools_return_path(self):
        for tool in ("read_file", "write_file", "read_document", "ls"):
            assert subject_for_tool(tool, {"path": "/tmp/foo.pdf"}) == "/tmp/foo.pdf"

    def test_pattern_tools_return_pattern(self):
        assert subject_for_tool("glob", {"pattern": "**/*.py"}) == "**/*.py"

    def test_unknown_tool_returns_wildcard(self):
        assert subject_for_tool("todo_write", {"todos": []}) == "*"


# ---------------------------------------------------------------------------
# check_tool_allowed — semántica básica
# ---------------------------------------------------------------------------

class TestCheckToolAllowed:
    def test_empty_settings_allows_everything(self):
        s = ToolSettings.empty()
        allowed, _ = check_tool_allowed(s, "bash", {"command": "ls"})
        assert allowed is True

    def test_deny_blocks_matching_command(self):
        s = ToolSettings(deny={"bash": ["rm *"]})
        allowed, reason = check_tool_allowed(s, "bash", {"command": "rm -rf ."})
        assert allowed is False
        assert "deny" in reason
        assert "rm *" in reason

    def test_deny_does_not_block_nonmatching(self):
        s = ToolSettings(deny={"bash": ["rm *"]})
        allowed, _ = check_tool_allowed(s, "bash", {"command": "git status"})
        assert allowed is True

    def test_allow_list_blocks_unmatched_path(self):
        s = ToolSettings(allow={"read_document": ["**/*.pdf", "**/*.docx"]})
        allowed, reason = check_tool_allowed(
            s, "read_document", {"path": "secreto.env"}
        )
        assert allowed is False
        assert "allow" in reason

    def test_allow_list_permits_matched_path_with_dir(self):
        s = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        allowed, _ = check_tool_allowed(
            s, "read_document", {"path": "docs/informe.pdf"}
        )
        assert allowed is True

    def test_allow_list_permits_matched_path_bare_filename(self):
        """** debe cubrir también archivos sin directorio (cero segmentos)."""
        s = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        allowed, _ = check_tool_allowed(
            s, "read_document", {"path": "informe.pdf"}
        )
        assert allowed is True

    def test_allow_prefixed_pattern_does_not_match_outside_prefix(self):
        """Un patrón con prefijo concreto NO debe permitir rutas fuera de ese prefijo.

        Regresión: el fallback de bare-filename se aplicaba también a patrones
        con prefijo (ej: '.ci2lab/output/**/*.docx'), permitiendo cualquier .docx
        independientemente de su directorio.
        """
        s = ToolSettings(
            allow={"fill_docx_template": [".ci2lab/documents/output/**/*.docx"]}
        )
        # Ruta fuera del prefijo -> debe bloquearse
        allowed, reason = check_tool_allowed(
            s, "fill_docx_template", {"output": "cualquier_sitio/malicioso.docx"}
        )
        assert allowed is False, f"Debería estar bloqueado, pero se permitió: {reason}"

    def test_allow_prefixed_pattern_permits_inside_prefix(self):
        """Un patrón con prefijo concreto SÍ debe permitir rutas dentro de ese prefijo."""
        s = ToolSettings(
            allow={"fill_docx_template": [".ci2lab/documents/output/**/*.docx"]}
        )
        allowed, _ = check_tool_allowed(
            s,
            "fill_docx_template",
            {"output": ".ci2lab/documents/output/informe.docx"},
        )
        assert allowed is True

    def test_tool_not_in_allow_is_permitted_by_default(self):
        s = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        # bash no aparece en allow → permitido por defecto
        allowed, _ = check_tool_allowed(s, "bash", {"command": "ls"})
        assert allowed is True

    def test_deny_wins_over_allow(self):
        """Deny es jerárquicamente superior: si está en deny, no importa allow."""
        s = ToolSettings(
            allow={"bash": ["*"]},
            deny={"bash": ["rm *"]},
        )
        allowed, reason = check_tool_allowed(s, "bash", {"command": "rm -rf ."})
        assert allowed is False
        assert "deny" in reason

    def test_allow_star_permits_all(self):
        s = ToolSettings(allow={"bash": ["*"]})
        allowed, _ = check_tool_allowed(s, "bash", {"command": "cualquier cosa"})
        assert allowed is True

    def test_deny_extension_pattern(self):
        s = ToolSettings(deny={"read_file": ["*.env", "**/.env"]})
        allowed, _ = check_tool_allowed(s, "read_file", {"path": ".env"})
        assert allowed is False

    def test_deny_nested_env_path(self):
        s = ToolSettings(deny={"read_file": ["**/.env"]})
        allowed, _ = check_tool_allowed(
            s, "read_file", {"path": "config/.env"}
        )
        assert allowed is False


# ---------------------------------------------------------------------------
# Fusión de capas (_merge)
# ---------------------------------------------------------------------------

class TestMerge:
    def test_deny_accumulates(self):
        g = ToolSettings(deny={"bash": ["rm *"]})
        p = ToolSettings(deny={"bash": ["del *"]})
        merged = _merge(g, p)
        assert "rm *" in merged.deny["bash"]
        assert "del *" in merged.deny["bash"]

    def test_deny_global_cannot_be_removed_by_project(self):
        g = ToolSettings(deny={"bash": ["rm *"]})
        p = ToolSettings(deny={})   # proyecto no define bash deny
        merged = _merge(g, p)
        assert "rm *" in merged.deny["bash"]

    def test_allow_project_overrides_global_for_same_tool(self):
        g = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        p = ToolSettings(allow={"read_document": ["**/*.pdf", "**/*.docx"]})
        merged = _merge(g, p)
        assert "**/*.docx" in merged.allow["read_document"]

    def test_allow_global_preserved_if_project_does_not_define(self):
        g = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        p = ToolSettings(allow={})
        merged = _merge(g, p)
        assert "**/*.pdf" in merged.allow["read_document"]

    def test_deny_no_duplicates(self):
        g = ToolSettings(deny={"bash": ["rm *", "del *"]})
        p = ToolSettings(deny={"bash": ["del *", "Remove-Item *"]})
        merged = _merge(g, p)
        counts = merged.deny["bash"].count("del *")
        assert counts == 1


# ---------------------------------------------------------------------------
# load_settings — lectura desde disco
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_empty_when_no_files(self, tmp_path, monkeypatch):
        # Aislar home: sin ~/.ci2lab/settings.json real
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        s = load_settings(str(tmp_path))
        assert s.allow == {}
        assert s.deny == {}

    def test_loads_project_settings(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        _write_settings(
            tmp_path / ".ci2lab" / "settings.json",
            {"deny": {"bash": ["rm *"]}},
        )
        s = load_settings(str(tmp_path))
        assert "rm *" in s.deny.get("bash", [])

    def test_invalid_json_ignored(self, tmp_path, monkeypatch):
        # El JSON del proyecto es inválido; el global tampoco existe (home aislado)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        ci2lab_dir = tmp_path / ".ci2lab"
        ci2lab_dir.mkdir()
        (ci2lab_dir / "settings.json").write_text("{invalid json", encoding="utf-8")
        s = load_settings(str(tmp_path))
        assert s.allow == {}
        assert s.deny == {}

    def test_global_and_project_merged(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        _write_settings(
            fake_home / ".ci2lab" / "settings.json",
            {"deny": {"bash": ["rm *"]}},
        )
        project = tmp_path / "project"
        project.mkdir()
        _write_settings(
            project / ".ci2lab" / "settings.json",
            {"deny": {"bash": ["del *"]}, "allow": {"read_document": ["**/*.pdf"]}},
        )
        s = load_settings(str(project))
        assert "rm *" in s.deny["bash"]
        assert "del *" in s.deny["bash"]
        assert "**/*.pdf" in s.allow["read_document"]

    def test_string_pattern_normalized_to_list(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        _write_settings(
            tmp_path / ".ci2lab" / "settings.json",
            {"deny": {"bash": "rm *"}},   # string en lugar de lista
        )
        s = load_settings(str(tmp_path))
        assert s.deny["bash"] == ["rm *"]

    def test_unknown_top_keys_ignored(self, tmp_path):
        _write_settings(
            tmp_path / ".ci2lab" / "settings.json",
            {"allow": {}, "deny": {}, "ask": {"bash": ["*"]}},
        )
        s = load_settings(str(tmp_path))
        assert not hasattr(s, "ask")
