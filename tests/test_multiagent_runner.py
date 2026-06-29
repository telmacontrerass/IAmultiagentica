from unittest.mock import patch

from ci2lab.harness import AgentConfig, default_selection
from ci2lab.harness.multiagent import AgentRole, run_subagent
from ci2lab.harness.multiagent.runner import (
    ROLE_MAX_ROUNDS,
    build_role_anchor,
    build_subagent_config,
    build_subagent_system_prompt,
)


def test_build_subagent_config_filters_tools_without_mutating_parent():
    parent = AgentConfig(cwd=".", stream=True, session_id="session-1")

    subagent = build_subagent_config(AgentRole.RESEARCHER, parent)

    assert parent.skill_allowed_tools is None
    assert parent.stream is True
    assert parent.session_id == "session-1"
    assert subagent.stream is False
    assert subagent.session_id is None
    assert subagent.skill_allowed_tools is not None
    assert "read_file" in subagent.skill_allowed_tools
    assert "write_file" not in subagent.skill_allowed_tools


def test_build_subagent_config_preserves_approval_scope_without_chat_session():
    parent = AgentConfig(
        cwd=".",
        stream=True,
        session_id="chat-session",
        approval_session_id="multiagent-run",
    )

    subagent = build_subagent_config(AgentRole.VALIDATOR, parent)

    assert subagent.session_id is None
    assert subagent.approval_session_id == "multiagent-run"


def test_build_subagent_config_applies_role_round_budget():
    parent = AgentConfig(cwd=".", max_rounds=25)

    planner = build_subagent_config(AgentRole.PLANNER, parent)
    researcher = build_subagent_config(AgentRole.RESEARCHER, parent)
    coder = build_subagent_config(AgentRole.PYTHON_CODER, parent)

    assert planner.max_rounds == ROLE_MAX_ROUNDS[AgentRole.PLANNER]
    assert researcher.max_rounds == ROLE_MAX_ROUNDS[AgentRole.RESEARCHER]
    assert coder.max_rounds == ROLE_MAX_ROUNDS[AgentRole.PYTHON_CODER]
    assert parent.max_rounds == 25


def test_build_subagent_config_never_exceeds_parent_round_budget():
    parent = AgentConfig(cwd=".", max_rounds=3)

    subagent = build_subagent_config(AgentRole.PYTHON_CODER, parent)

    assert subagent.max_rounds == 3


def test_build_subagent_config_intersects_skill_and_role_tools():
    parent = AgentConfig(
        cwd=".",
        stream=True,
        session_id="session-1",
        skill_allowed_tools=frozenset({"web_fetch", "read_file"}),
    )

    subagent = build_subagent_config(AgentRole.RESEARCHER, parent)

    assert parent.skill_allowed_tools == frozenset({"web_fetch", "read_file"})
    assert subagent.skill_allowed_tools == frozenset({"read_file"})
    assert "web_fetch" not in subagent.skill_allowed_tools
    assert "grep" not in subagent.skill_allowed_tools


def test_build_subagent_config_keeps_empty_intersection_blocked():
    parent = AgentConfig(
        cwd=".",
        skill_allowed_tools=frozenset({"web_fetch"}),
    )

    subagent = build_subagent_config(AgentRole.RESEARCHER, parent)

    assert subagent.skill_allowed_tools == frozenset()


def test_subagent_system_prompt_includes_english_role_purpose():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".")

    prompt = build_subagent_system_prompt(
        AgentRole.RESEARCHER,
        selection,
        config,
    )

    assert "## Role Anchor" in prompt
    assert "You are currently acting as researcher." in prompt
    assert "Your purpose in this phase is: Gather evidence" in prompt
    assert "Do not implement changes" in prompt
    assert "Expected output:" in prompt


def test_coder_prompt_without_bash_forbids_shell_creation_commands():
    selection = default_selection("test:1b")
    config = build_subagent_config(
        AgentRole.PYTHON_CODER,
        AgentConfig(cwd="."),
    )

    prompt = build_subagent_system_prompt(
        AgentRole.PYTHON_CODER,
        selection,
        config,
    )

    assert "## Allowed Tools For This Phase" in prompt
    assert "`bash` is not available in this phase" in prompt
    assert "Do not use `bash`, `mkdir`, `cd`, `touch`, or `tree`" in prompt
    allowed_line = prompt.split("## Allowed Tools For This Phase", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "`bash`" not in allowed_line


def test_coder_prompt_without_todo_write_removes_absolute_todo_requirement():
    selection = default_selection("test:1b")
    config = build_subagent_config(
        AgentRole.PYTHON_CODER,
        AgentConfig(cwd="."),
    )

    prompt = build_subagent_system_prompt(
        AgentRole.PYTHON_CODER,
        selection,
        config,
    )

    assert (
        "For any task with more than one step, plan it with `todo_write` BEFORE acting"
        not in prompt
    )
    assert "## Allowed Tools For This Phase" in prompt
    assert "`todo_write` is not available in this phase" in prompt


def test_validator_prompt_lists_git_status_and_git_diff_when_allowed():
    selection = default_selection("test:1b")
    config = build_subagent_config(
        AgentRole.VALIDATOR,
        AgentConfig(cwd="."),
    )

    prompt = build_subagent_system_prompt(
        AgentRole.VALIDATOR,
        selection,
        config,
    )
    allowed_line = prompt.split("## Allowed Tools For This Phase", 1)[1].split(
        "\n\n", 1
    )[0]

    assert "`git_status`" in allowed_line
    assert "`git_diff`" in allowed_line


def test_run_subagent_uses_isolated_system_context_and_role_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=True, session_id="session-1")

    with patch("ci2lab.harness.multiagent.runner.run_agent") as mock_run_agent:
        mock_run_agent.return_value = "plan ready"

        result = run_subagent(
            AgentRole.PLANNER,
            "Plan this change",
            selection,
            config,
        )

    assert result.role == AgentRole.PLANNER
    assert result.task == "Plan this change"
    assert result.output == "plan ready"

    _, args, kwargs = mock_run_agent.mock_calls[0]
    assert args[0] == "Plan this change"
    subagent_config = kwargs["config"]
    messages = kwargs["messages"]

    assert subagent_config is not config
    assert subagent_config.session_id is None
    assert subagent_config.stream is False
    assert subagent_config.skill_allowed_tools == frozenset()
    assert subagent_config.role_anchor == build_role_anchor(AgentRole.PLANNER)
    assert len(messages) == 1
    assert messages[0]["role"] == "system"
    assert "Role: planner" in messages[0]["content"]
    assert "You are currently acting as planner." in messages[0]["content"]
    assert "isolated subagent context" in messages[0]["content"]
    assert "BLOCKED:" in messages[0]["content"]
    assert "Do not keep retrying the same action" in messages[0]["content"]


def test_subagent_role_anchor_is_passed_to_run_agent():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=True)

    with patch("ci2lab.harness.multiagent.runner.run_agent") as mock_run_agent:
        mock_run_agent.return_value = "done"

        run_subagent(
            AgentRole.VALIDATOR,
            "Validate this change",
            selection,
            config,
        )

    _, _, kwargs = mock_run_agent.mock_calls[0]
    subagent_config = kwargs["config"]
    assert subagent_config.role_anchor == build_role_anchor(AgentRole.VALIDATOR)
    assert "Validate the current result using tests or deterministic checks." in subagent_config.role_anchor


def test_run_subagent_passes_user_selected_model_to_run_agent():
    selection = default_selection("user-selected:7b")
    config = AgentConfig(cwd=".")

    with patch("ci2lab.harness.multiagent.runner.run_agent") as mock_run_agent:
        mock_run_agent.return_value = "done"

        run_subagent(
            AgentRole.RESEARCHER,
            "Research this",
            selection,
            config,
        )

    _, args, kwargs = mock_run_agent.mock_calls[0]
    assert args[1] is selection
    assert kwargs["messages"][0]["content"].count("user-selected:7b") >= 1


def test_run_subagent_captures_internal_console_output(capsys):
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=True, session_id="session-1")

    def noisy_run_agent(*args, **kwargs):
        from ci2lab.console import console

        console.print("internal subagent output")
        return "captured result"

    with patch("ci2lab.harness.multiagent.runner.run_agent", side_effect=noisy_run_agent):
        result = run_subagent(
            AgentRole.REVIEWER,
            "Review this",
            selection,
            config,
        )

    assert result.output == "captured result"
    assert "internal subagent output" not in capsys.readouterr().out


def test_run_subagent_shows_full_output_when_interactive(capsys):
    # With a progress sink attached (interactive REPL), the subagent's reasoning
    # and tool calls must be visible — not captured — so the user can see what
    # each role is doing and what a permission prompt is for.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, run_log_enabled=False)

    def noisy_run_agent(*args, **kwargs):
        from ci2lab.console import console

        console.print("internal subagent reasoning")
        return "result"

    with patch("ci2lab.harness.multiagent.runner.run_agent", side_effect=noisy_run_agent):
        run_subagent(
            AgentRole.RESEARCHER,
            "Research this",
            selection,
            config,
            on_progress=lambda _label: None,
        )

    assert "internal subagent reasoning" in capsys.readouterr().out


def test_run_subagent_forwards_concise_progress_while_output_is_captured(capsys):
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, run_log_enabled=False)

    def progressing_run_agent(*args, **kwargs):
        kwargs["on_progress"]("Searching the project files...")
        kwargs["on_progress"]("Reviewing the latest results...")
        return "done"

    with patch(
        "ci2lab.harness.multiagent.runner.run_agent",
        side_effect=progressing_run_agent,
    ):
        run_subagent(
            AgentRole.RESEARCHER,
            "Research this",
            selection,
            config,
        )

    output = capsys.readouterr().out
    assert "[multi-agent:researcher] Searching the project files..." in output
    assert "[multi-agent:researcher] Reviewing the latest results..." in output


def test_subagent_does_not_clear_parent_progress_before_final_answer():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, run_log_enabled=False)
    progress: list[str] = []

    def progressing_run_agent(*args, **kwargs):
        kwargs["on_progress"]("Searching the project files...")
        kwargs["on_progress"]("")
        return "done"

    with patch(
        "ci2lab.harness.multiagent.runner.run_agent",
        side_effect=progressing_run_agent,
    ):
        run_subagent(
            AgentRole.RESEARCHER,
            "Research this",
            selection,
            config,
            on_progress=progress.append,
        )

    assert progress == ["researcher: Searching the project files..."]
