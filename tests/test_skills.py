"""Tests for workspace skills loading and invocation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ci2lab.harness import default_selection
from ci2lab.harness.repl import run_repl
from ci2lab.harness.skills.loader import load_skills, skills_for_model
from ci2lab.harness.tools.registry import execute_tool, get_function_schemas
from ci2lab.harness.tools.skill_tool import invoke_skill
from ci2lab.harness.types import AgentConfig, ToolCall


@pytest.fixture
def workspace_with_skill(tmp_path: Path) -> Path:
    skill_dir = tmp_path / ".ci2lab" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: demo-skill
description: Demo workflow
when_to_use: Testing
allowed-tools: bash write_file
disable-model-invocation: false
---
# Steps
1. Run bash
2. Write output
""",
        encoding="utf-8",
    )
    return tmp_path


def test_load_skills_from_workspace(workspace_with_skill: Path) -> None:
    skills = load_skills(str(workspace_with_skill))
    assert "demo-skill" in skills
    skill = skills["demo-skill"]
    assert skill.description == "Demo workflow"
    assert skill.allowed_tools == ["bash", "write_file"]
    assert "Run bash" in skill.body


def test_skills_for_model_hides_disabled(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".ci2lab" / "skills" / "hidden"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: hidden
description: Hidden
disable-model-invocation: true
---
body
""",
        encoding="utf-8",
    )
    all_skills = load_skills(str(tmp_path))
    visible = skills_for_model(all_skills)
    assert "hidden" not in visible


def test_invoke_skill_sets_allowed_tools(workspace_with_skill: Path) -> None:
    cfg = AgentConfig(cwd=str(workspace_with_skill))
    output = invoke_skill(cfg, "demo-skill", "hello")
    assert "Skill: demo-skill" in output
    assert cfg.skill_allowed_tools == frozenset({"bash", "write_file"})


def test_get_function_schemas_filters_by_skill(workspace_with_skill: Path) -> None:
    cfg = AgentConfig(cwd=str(workspace_with_skill))
    cfg.skill_allowed_tools = frozenset({"bash", "write_file"})
    names = {s["function"]["name"] for s in get_function_schemas(cfg)}
    assert "bash" in names
    assert "write_file" in names
    assert "grep" not in names


def test_execute_skill_tool(workspace_with_skill: Path) -> None:
    cfg = AgentConfig(cwd=str(workspace_with_skill))
    result = execute_tool(
        ToolCall(name="skill", arguments={"skill_name": "demo-skill"}),
        cfg,
    )
    assert not result.is_error
    assert "demo-skill" in result.content


def test_builtin_research_skills_available() -> None:
    skills = load_skills(".")
    assert "research_web_doc_review" in skills
    assert "research_web_vs_repo" in skills


def test_repl_slash_skill_forwards_url_argument(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".ci2lab" / "skills" / "research_web_doc_review"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: research_web_doc_review
description: Review URL
allowed-tools: web_fetch
---
Body
""",
        encoding="utf-8",
    )
    cfg = AgentConfig(cwd=str(tmp_path), stream=False, run_log_enabled=False)
    selection = default_selection("test:1b")
    url = "https://docs.python.org/3/library/pathlib.html"

    with (
        patch("ci2lab.harness.repl.read_prompt_line", side_effect=[
            f"/research_web_doc_review {url}",
            "/exit",
        ]),
        patch("ci2lab.harness.repl.run_agent") as mock_run_agent,
        patch("ci2lab.harness.repl.console.print"),
    ):
        run_repl(selection, cfg, session_id="test-session")

    assert mock_run_agent.call_count == 1
    forwarded_prompt = mock_run_agent.call_args.args[0]
    assert "Arguments: https://docs.python.org/3/library/pathlib.html" in forwarded_prompt
    assert "User request: URL: https://docs.python.org/3/library/pathlib.html" in forwarded_prompt
