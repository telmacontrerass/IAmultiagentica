"""Tests for ci2lab/settings.py."""

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
# check_tool_allowed — basic semantics
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
            s, "read_document", {"path": "secret.env"}
        )
        assert allowed is False
        assert "allow" in reason

    def test_allow_list_permits_matched_path_with_dir(self):
        s = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        allowed, _ = check_tool_allowed(
            s, "read_document", {"path": "docs/report.pdf"}
        )
        assert allowed is True

    def test_allow_list_permits_matched_path_bare_filename(self):
        """** must also cover files with no directory (zero segments)."""
        s = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        allowed, _ = check_tool_allowed(
            s, "read_document", {"path": "report.pdf"}
        )
        assert allowed is True

    def test_allow_prefixed_pattern_does_not_match_outside_prefix(self):
        """A pattern with a concrete prefix must NOT allow paths outside that prefix.

        Regression: the bare-filename fallback was also applied to patterns
        with a prefix (e.g. '.ci2lab/output/**/*.docx'), allowing any .docx
        regardless of its directory.
        """
        s = ToolSettings(
            allow={"fill_docx_template": [".ci2lab/documents/output/**/*.docx"]}
        )
        # Path outside the prefix -> must be blocked
        allowed, reason = check_tool_allowed(
            s, "fill_docx_template", {"output": "anywhere/malicious.docx"}
        )
        assert allowed is False, f"Should be blocked, but it was allowed: {reason}"

    def test_allow_prefixed_pattern_permits_inside_prefix(self):
        """A pattern with a concrete prefix MUST allow paths inside that prefix."""
        s = ToolSettings(
            allow={"fill_docx_template": [".ci2lab/documents/output/**/*.docx"]}
        )
        allowed, _ = check_tool_allowed(
            s,
            "fill_docx_template",
            {"output": ".ci2lab/documents/output/report.docx"},
        )
        assert allowed is True

    def test_tool_not_in_allow_is_permitted_by_default(self):
        s = ToolSettings(allow={"read_document": ["**/*.pdf"]})
        # bash does not appear in allow → permitted by default
        allowed, _ = check_tool_allowed(s, "bash", {"command": "ls"})
        assert allowed is True

    def test_deny_wins_over_allow(self):
        """Deny is hierarchically superior: if it is in deny, allow does not matter."""
        s = ToolSettings(
            allow={"bash": ["*"]},
            deny={"bash": ["rm *"]},
        )
        allowed, reason = check_tool_allowed(s, "bash", {"command": "rm -rf ."})
        assert allowed is False
        assert "deny" in reason

    def test_allow_star_permits_all(self):
        s = ToolSettings(allow={"bash": ["*"]})
        allowed, _ = check_tool_allowed(s, "bash", {"command": "anything"})
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
# Layer merging (_merge)
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
        p = ToolSettings(deny={})   # project does not define bash deny
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
# load_settings — reading from disk
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_empty_when_no_files(self, tmp_path, monkeypatch):
        # Isolate home: no real ~/.ci2lab/settings.json
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
        # The project JSON is invalid; the global one does not exist either (isolated home)
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
            {"deny": {"bash": "rm *"}},   # string instead of list
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
