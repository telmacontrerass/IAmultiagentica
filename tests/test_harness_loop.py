from unittest.mock import MagicMock, patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.query.loop import (
    _agent_can_write_files,
    _initial_progress_label,
    _model_progress_label,
    _prepend_missing_reads,
    _tool_progress_label,
)
from ci2lab.harness.token_usage import TokenUsage
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import ToolCall, ToolResult


def test_agent_can_write_files_gates_on_effective_allowlist():
    # Regression: read-only roles (researcher/reviewer/planner/validator) were
    # nudged to "call write_file" they could not run, derailing the role. The
    # gate must reflect the effective tool allow-list, not the prompt wording.
    from ci2lab.harness.multiagent.roles import EDIT_TOOLS, READ_TOOLS, RUNTIME_TOOLS

    # No skill/role restriction -> full tool set -> can write.
    assert _agent_can_write_files(AgentConfig(cwd=".")) is True
    # Coder roles carry the file-writing tools.
    assert _agent_can_write_files(AgentConfig(cwd=".", skill_allowed_tools=EDIT_TOOLS)) is True
    # Read-only and runtime-only roles cannot write files.
    assert _agent_can_write_files(AgentConfig(cwd=".", skill_allowed_tools=READ_TOOLS)) is False
    assert _agent_can_write_files(AgentConfig(cwd=".", skill_allowed_tools=RUNTIME_TOOLS)) is False
    # The toolless planner cannot write either.
    assert _agent_can_write_files(AgentConfig(cwd=".", skill_allowed_tools=frozenset())) is False
    # Synonyms canonicalize, so an `edit` allow-list still counts as writable.
    assert (
        _agent_can_write_files(AgentConfig(cwd=".", skill_allowed_tools=frozenset({"edit"})))
        is True
    )


def test_initial_progress_label_describes_user_visible_work():
    assert _initial_progress_label("summarize test.pdf") == "Preparing to read the document..."
    assert _initial_progress_label("fix this test") == "Planning the code change..."
    assert _initial_progress_label("corrige esta prueba") == "Planning the code change..."
    assert (
        _initial_progress_label("what is the latest price?")
        == "Checking what information is needed..."
    )
    assert _initial_progress_label("hello") == "Deciding the next step..."
    assert (
        _initial_progress_label("lista los archivos del repositorio")
        == "Inspecting the relevant project context..."
    )
    assert _initial_progress_label("hola") == "Deciding the next step..."


def test_spanish_prompts_still_produce_english_progress_labels():
    assert _initial_progress_label("lee este documento") == ("Preparing to read the document...")
    assert _initial_progress_label("busca información actual en internet") == (
        "Checking what information is needed..."
    )
    assert _initial_progress_label("corrige esta prueba") == ("Planning the code change...")
    assert _initial_progress_label("revisa los archivos del repositorio") == (
        "Inspecting the relevant project context..."
    )


def test_local_pdf_to_pptx_loop_accepts_read_document_then_write_pptx():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )
    read = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "read_document",
                    "arguments": '{"path": "informe.pdf"}',
                },
            }
        ],
    )
    write = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c2",
                "function": {
                    "name": "write_pptx",
                    "arguments": (
                        '{"output_path": "outputs/informe.pptx", "title": "Informe", '
                        '"slides": [{"type": "cover", "title": "Informe"}, '
                        '{"type": "bullets", "title": "Resumen", "bullets": ["Dato del PDF"]}]}'
                    ),
                },
            }
        ],
    )
    final = LLMResponse(content="Created outputs/informe.pptx.", tool_calls=[])
    executed: list[str] = []

    def fake_execute(call: ToolCall, _config: AgentConfig) -> ToolResult:
        executed.append(call.name)
        if call.name == "read_document":
            return ToolResult(
                tool_name="read_document",
                content="[PDF text] Dato del PDF",
                is_error=False,
                call_id=call.call_id,
            )
        return ToolResult(
            tool_name="write_pptx",
            content='{"written_file": "outputs/informe.pptx", "slide_count": 2}',
            is_error=False,
            call_id=call.call_id,
            outcome="approved",
        )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [read, write, final]
        result = run_agent(
            "Crea una presentaci\u00f3n PowerPoint editable a partir del PDF local informe.pdf",
            selection,
            config=config,
        )

    assert executed == ["read_document", "write_pptx"]
    assert "outputs/informe.pptx" in result


def test_write_pptx_success_for_requested_output_finalizes_without_retry():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )
    write = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "write_pptx",
                    "arguments": (
                        '{"output_path": "demo_presentacion.pptx", "title": "Demo", '
                        '"slides": [{"type": "cover", "title": "Demo"}, '
                        '{"type": "bullets", "title": "Resumen", "bullets": ["Dato real"]}]}'
                    ),
                },
            }
        ],
    )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="write_pptx",
                content='{"written_file": "demo_presentacion.pptx", "slide_count": 2}',
                is_error=False,
                call_id="c1",
                outcome="approved",
            ),
        ) as exec_mock,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [write]
        result = run_agent(
            "Crea una presentacion PowerPoint desde informe.pdf. "
            "Guarda el resultado como demo_presentacion.pptx.",
            selection,
            config=config,
        )

    assert client.chat.call_count == 1
    assert exec_mock.call_count == 1
    assert "demo_presentacion.pptx" in result
    assert "write_pptx" in result


def test_write_pptx_placeholder_document_content_gets_nudged_before_finalizing():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )
    placeholder_write = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "write_pptx",
                    "arguments": (
                        '{"output_path": "demo_presentacion.pptx", "title": "Demo", '
                        '"slides": [{"type": "cover", "title": "Demo"}, '
                        '{"type": "bullets", "title": "Contenido", '
                        '"bullets": ["Punto 1", "Punto 2"]}]}'
                    ),
                },
            }
        ],
    )
    corrected_write = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c2",
                "function": {
                    "name": "write_pptx",
                    "arguments": (
                        '{"output_path": "demo_presentacion.pptx", "title": "Demo", '
                        '"overwrite": true, '
                        '"slides": [{"type": "cover", "title": "Demo"}, '
                        '{"type": "bullets", "title": "Coste de hardware", '
                        '"bullets": ["H100/H200 condicionan el presupuesto", '
                        '"La memoria disponible limita los modelos grandes"]}]}'
                    ),
                },
            }
        ],
    )
    executed_args: list[dict] = []

    def fake_execute(call: ToolCall, _config: AgentConfig) -> ToolResult:
        executed_args.append(call.arguments)
        return ToolResult(
            tool_name="write_pptx",
            content='{"written_file": "demo_presentacion.pptx", "slide_count": 2}',
            is_error=False,
            call_id=call.call_id,
            outcome="approved",
        )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [placeholder_write, corrected_write]
        result = run_agent(
            "Crea una presentacion PowerPoint editable a partir del PDF local informe.pdf. "
            "Usa unicamente el contenido del documento. "
            "Guarda el resultado como demo_presentacion.pptx.",
            selection,
            config=config,
        )

    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user" and "Use concrete facts/headings/terms" in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )
    assert len(executed_args) == 2
    assert executed_args[1]["overwrite"] is True
    assert "demo_presentacion.pptx" in result


def test_model_progress_label_explains_later_rounds():
    assert _model_progress_label("fix this test", 1) == "Planning the code change..."
    assert (
        _model_progress_label("fix this test", 2)
        == "Reviewing the latest results and deciding the next step..."
    )


def test_tool_progress_label_uses_real_tool_work():
    assert (
        _tool_progress_label(
            [ToolCall(name="read_file", arguments={"path": "paper.pdf"}, call_id="c1")]
        )
        == "Extracting information from the PDF..."
    )
    assert (
        _tool_progress_label(
            [ToolCall(name="apply_patch", arguments={"patch": "*** Begin Patch"}, call_id="c1")]
        )
        == "Generating code changes..."
    )
    assert (
        _tool_progress_label(
            [ToolCall(name="web_search", arguments={"query": "latest release"}, call_id="c1")]
        )
        == "Looking up current information..."
    )


def test_run_agent_single_turn_no_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    mock_response = LLMResponse(content="Done, here is the summary.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = mock_response
        result = run_agent("summarize the project", selection, config=config)

    assert "summary" in result.lower()


def test_require_tool_execution_rejects_text_only_answer():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        max_rounds=2,
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        require_tool_execution=True,
        verify_final_answer=False,
    )
    response = LLMResponse(content="42", tool_calls=[])
    with patch("ci2lab.harness.query.loop.call_llm", return_value=response):
        result = run_agent("calculate", selection, config=config)
    assert result.startswith("REQUIRED_TOOL_NOT_EXECUTED")


def test_rejected_tool_call_does_not_satisfy_requirement():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        max_rounds=2,
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        require_tool_execution=True,
        verify_final_answer=False,
    )
    response = LLMResponse(
        content="",
        tool_calls=[
            {"id": "c1", "function": {"name": "read_file", "arguments": '{"path":"missing"}'}}
        ],
    )
    with (
        patch("ci2lab.harness.query.loop.call_llm", return_value=response),
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="read_file",
                content="rejected",
                is_error=True,
                outcome="blocked_by_policy",
            ),
        ),
    ):
        result = run_agent("inspect", selection, config=config)
    assert result.startswith("REQUIRED_TOOL_NOT_EXECUTED")


def test_successful_tool_execution_satisfies_requirement_after_retry():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        max_rounds=4,
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        require_tool_execution=True,
        verify_final_answer=False,
    )
    text = LLMResponse(content="I can answer directly", tool_calls=[])
    call = LLMResponse(
        content="",
        tool_calls=[
            {"id": "c1", "function": {"name": "read_file", "arguments": '{"path":"README.md"}'}}
        ],
    )
    final = LLMResponse(content="verified", tool_calls=[])
    with (
        patch("ci2lab.harness.query.loop.call_llm", side_effect=[text, call, final]),
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="read_file", content="ok", is_error=False, outcome="approved"
            ),
        ),
    ):
        result = run_agent("inspect", selection, config=config)
    assert result == "verified"


def test_run_agent_replaces_generic_thinking_with_task_progress():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    response = LLMResponse(content="Cambio preparado.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.call_llm", return_value=response),
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        run_agent("fix this test", selection, config=config)

    printed = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    assert any("Planning the code change..." in message for message in printed)
    assert not any("Thinking..." in message for message in printed)


def test_run_agent_can_forward_progress_to_chat_callback():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    response = LLMResponse(content="Cambio preparado.", tool_calls=[])
    progress: list[str] = []

    with patch("ci2lab.harness.query.loop.call_llm", return_value=response):
        run_agent(
            "fix this test",
            selection,
            config=config,
            on_progress=progress.append,
        )

    # A write request answered in prose with zero tool calls gets two recovery
    # rounds before the answer is accepted: the described-but-not-written nudge
    # first, then the ungrounded-answer nudge (nothing was ever attempted).
    assert progress == [
        "Planning the code change...",
        "Reviewing the latest results and deciding the next step...",
        "Reviewing the latest results and deciding the next step...",
        "Finalizing the answer...",
        "",
    ]


def test_run_agent_accumulates_token_usage_across_rounds():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "ls", "arguments": '{"path": "."}'},
            }
        ],
        usage=TokenUsage(
            prompt_tokens=10,
            completion_tokens=3,
            total_tokens=13,
            model="test:1b",
        ),
    )
    final = LLMResponse(
        content="There are several files.",
        tool_calls=[],
        usage=TokenUsage(
            prompt_tokens=20,
            completion_tokens=4,
            total_tokens=24,
            model="test:1b",
        ),
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent("list files", selection, config=config)

    assert config.token_usage.turn.prompt_tokens == 30
    assert config.token_usage.turn.completion_tokens == 7
    assert config.token_usage.turn.total_tokens == 37
    assert config.token_usage.session.total_tokens == 37


def test_run_agent_executes_tool_then_answers():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "ls", "arguments": '{"path": "."}'},
            }
        ],
    )
    final = LLMResponse(content="There are several files.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        result = run_agent("list files", selection, config=config)

    assert "files" in result.lower()
    assert client.chat.call_count == 2


def test_run_agent_stream_true_prints_final_text_when_not_streamed():
    selection = default_selection("test:1b")
    selection.supports_tools = True
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    final = LLMResponse(content="hello world", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.call_llm", return_value=final),
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        result = run_agent("Reply exactly: hello world", selection, config=config)

    assert result == "hello world"
    printed_texts = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    assert any("hello world" in text for text in printed_texts)


def test_run_agent_prints_model_text_before_tool_execution():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="I will inspect the workspace first.",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "ls", "arguments": '{"path": "."}'},
            }
        ],
    )
    final = LLMResponse(content="There are several files.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent("list files", selection, config=config)

    printed_texts = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    assert any("Model:" in text and "inspect the workspace" in text for text in printed_texts)


def test_run_agent_nudges_web_search_once_after_no_internet_reply():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    first = LLMResponse(
        content="I do not have access to the internet right now.",
        tool_calls=[],
    )
    second = LLMResponse(content="Got it, I will use web_search.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [first, second]
        result = run_agent("give me a live result", selection, config=config)

    assert "i will use web_search" in result.lower()
    assert client.chat.call_count == 2
    second_turn_messages = client.chat.call_args_list[1].args[0]
    nudge_messages = [
        m.get("content", "")
        for m in second_turn_messages
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    assert (
        sum(
            "You can use `web_search` for live info without a URL" in str(msg)
            for msg in nudge_messages
        )
        == 1
    )


def test_run_agent_shows_model_reply_before_a_nudge():
    # Insight: the model's prose must be visible even on rounds the loop nudges
    # instead of finalizing — otherwise the user only sees the system nudge and
    # never what the agent actually said.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    first = LLMResponse(
        content="I do not have access to the internet right now.",
        tool_calls=[],
    )
    second = LLMResponse(content="Got it, I will use web_search.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [first, second]
        run_agent("give me a live result", selection, config=config)

    printed_texts = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    # The first-round reply is surfaced as a "Model:" line before the nudge.
    assert any(
        "Model:" in text and "do not have access to the internet" in text for text in printed_texts
    )


def test_run_agent_does_not_reuse_false_success_text_before_tool_result():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="Result: Command executed successfully. Removed file.txt.",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "bash", "arguments": '{"command": "rm file.txt"}'},
            }
        ],
    )
    final = LLMResponse(content="The action was blocked by the security policy.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        result = run_agent("delete file.txt", selection, config=config)

    assert "blocked" in result.lower()
    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert not any(
        "executed successfully" in str(m.get("content", "")).lower()
        or "removed file.txt" in str(m.get("content", "")).lower()
        for m in second_turn_messages
        if isinstance(m, dict)
    )


def test_run_agent_loop_break_nudge_restates_original_prompt():
    selection = default_selection("test:1b")
    # This test asserts loop-break behavior, not context management. Give it a
    # large window so summarization (which also consumes a mocked chat response)
    # never fires and shifts the call indices — otherwise the assertion below is
    # coupled to the exact token size of the system prompt.
    selection.context_length = 1_000_000
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    original = "tell me the score of spains soccer match from yesterday"
    repeated_call = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "ls", "arguments": '{"path": "."}'},
            }
        ],
    )
    final = LLMResponse(content="There is no score in the available results.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [repeated_call, repeated_call, repeated_call, final]
        run_agent(original, selection, config=config)

    fourth_round_messages = client.chat.call_args_list[3].args[0]
    assert any(
        m.get("role") == "user"
        and "Original request:" in str(m.get("content", ""))
        and original in str(m.get("content", ""))
        for m in fourth_round_messages
    )


def test_prepend_missing_reads_before_edit():
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "Tests.py",
                "old_string": "a",
                "new_string": "b",
            },
        )
    ]
    result = _prepend_missing_reads(
        calls,
        "First read Tests.py, then change line 3",
    )
    assert len(result) == 2
    assert result[0].name == "read_file"
    assert result[0].arguments["path"] == "Tests.py"
    assert result[1].name == "edit_file"


def test_empty_bash_command_is_blocked(tmp_path):
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )

    result = execute_tool(
        ToolCall(name="bash", arguments={"command": "   "}, call_id="c1"),
        config,
    )

    assert result.is_error
    assert result.tool_name == "bash"
    assert "non-empty" in result.content.lower()


def test_local_repo_question_uses_tree_or_ls_not_empty_bash():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    first = LLMResponse(
        content='tree\n{"path": ".", "depth": 2, "max_entries": 100}',
        tool_calls=[],
    )
    final = LLMResponse(
        content=(
            "Main files: README.md, pyproject.toml, ci2lab/, tests/. "
            "The agent loop seems to be in ci2lab/harness/query/loop.py."
        ),
        tool_calls=[],
    )
    executed: list[ToolCall] = []

    def fake_execute_tool(call, _cfg):
        executed.append(call)
        return ToolResult(
            tool_name=call.name,
            content="ci2lab/\n  harness/\n    query/\n      loop.py\n",
            is_error=False,
            call_id=call.call_id,
        )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute_tool),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [first, final]
        result = run_agent(
            "List the main files of the repository and tell me in which folder the agent loop seems to be.",
            selection,
            config=config,
        )

    assert "loop.py" in result
    assert executed
    assert executed[0].name == "tree"
    assert executed[0].arguments == {"path": ".", "depth": 2, "max_entries": 100}
    assert all(call.name != "bash" for call in executed)


def test_final_answer_after_tree_stays_anchored_to_latest_user_prompt():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    prompt = (
        "List the main files of the repository and tell me in which folder "
        "the agent loop seems to be."
    )
    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "tree",
                    "arguments": '{"path": ".", "depth": 2, "max_entries": 100}',
                },
            }
        ],
    )
    final = LLMResponse(
        content="The loop seems to be in ci2lab/harness/query/loop.py.", tool_calls=[]
    )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="tree",
                content="ci2lab/harness/query/loop.py\n",
                is_error=False,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent(prompt, selection, config=config)

    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user"
        and "The user's current request is:" in str(m.get("content", ""))
        and prompt in str(m.get("content", ""))
        for m in second_turn_messages
    )


def test_role_anchor_reinjected_after_tool_round():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        role_anchor=(
            "Role anchor: You are currently acting as reviewer. "
            "Your purpose in this phase is: Review the completed result for bugs and gaps. "
            "Stay within this role. Do not implement changes. "
            "If blocked, report why instead of switching roles. "
            "Expected output: A concise review with findings."
        ),
    )
    prompt = "Review the result after checking the repository tree."
    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "tree",
                    "arguments": '{"path": ".", "depth": 2, "max_entries": 100}',
                },
            }
        ],
    )
    final = LLMResponse(content="Review complete: no major issues found.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="tree",
                content="ci2lab/harness/query/loop.py\n",
                is_error=False,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent(prompt, selection, config=config)

    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user"
        and "Role anchor: You are currently acting as reviewer." in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )
    assert any(
        m.get("role") == "user"
        and "The user's current request is:" in str(m.get("content", ""))
        and prompt in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )


def test_classic_loop_has_no_role_anchor_by_default():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "tree",
                    "arguments": '{"path": ".", "depth": 2, "max_entries": 100}',
                },
            }
        ],
    )
    final = LLMResponse(
        content="The loop seems to be in ci2lab/harness/query/loop.py.", tool_calls=[]
    )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="tree",
                content="ci2lab/harness/query/loop.py\n",
                is_error=False,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent("Find the harness loop.", selection, config=config)

    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert not any(
        m.get("role") == "user" and "Role anchor:" in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )


def test_context_summary_does_not_override_current_user_request():
    selection = default_selection("test:1b")
    selection.context_length = 8192
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    prompt = (
        "List the main files of the repository and tell me in which folder "
        "the agent loop seems to be."
    )
    old_messages = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "Old task: create docs/summary.md"},
        {"role": "assistant", "content": "I'll create docs/summary.md"},
    ]
    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "tree",
                    "arguments": '{"path": ".", "depth": 2, "max_entries": 100}',
                },
            }
        ],
    )
    final = LLMResponse(
        content="The loop seems to be in ci2lab/harness/query/loop.py.", tool_calls=[]
    )
    manage_calls = {"count": 0}

    def fake_manage_context(history, client, context_length, summary_failures=0):
        manage_calls["count"] += 1
        if manage_calls["count"] == 2:
            injected = list(history)
            injected.insert(
                1,
                {
                    "role": "user",
                    "content": "[Summary of earlier conversation]\n\nThe task was to create docs/summary.md",
                },
            )
            return (
                injected,
                summary_failures,
                ["Context: summarized history (~1000 → ~500 estimated tokens)."],
            )
        return history, summary_failures, []

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.manage_context", side_effect=fake_manage_context),
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="tree",
                content="ci2lab/harness/query/loop.py\n",
                is_error=False,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent(prompt, selection, config=config, messages=old_messages)

    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        "[Summary of earlier conversation]" in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )
    assert any(
        m.get("role") == "user"
        and "The user's current request is:" in str(m.get("content", ""))
        and prompt in str(m.get("content", ""))
        for m in second_turn_messages
    )


def test_repeated_read_only_call_is_served_from_cache():
    # A weak model re-issuing the identical successful read must NOT re-execute
    # the tool; it should get a short "already retrieved, move on" note so the
    # huge document text is not re-injected and progress continues.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    read = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "read_document", "arguments": '{"path": "doc.pdf"}'},
            }
        ],
    )
    read_again = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c2",
                "function": {"name": "read_document", "arguments": '{"path": "doc.pdf"}'},
            }
        ],
    )
    final = LLMResponse(content="Done following the document.", tool_calls=[])
    exec_mock = MagicMock(
        return_value=ToolResult(
            tool_name="read_document",
            content="FULL DOCUMENT TEXT",
            is_error=False,
            call_id="c1",
        )
    )
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", exec_mock),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [read, read_again, final]
        run_agent("read doc.pdf and follow the steps inside", selection, config=config)

    # The tool actually ran only once; the second identical read was cached.
    assert exec_mock.call_count == 1
    third_turn_messages = client.chat.call_args_list[2].args[0]
    assert any(
        "Already retrieved earlier in this turn" in str(m.get("content", ""))
        for m in third_turn_messages
        if isinstance(m, dict)
    )


def test_repeated_web_search_is_served_from_cache():
    # The reported failure: a weak model re-issues the same web_search every
    # round instead of answering from the first results. The second search (here
    # only differing by max_results) must be served from cache, not re-run, so
    # the model is pushed to answer instead of looping.
    selection = default_selection("test:1b")
    selection.context_length = 1_000_000
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    search = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query": "Spain vs Saudi Arabia result", "max_results": 5}',
                },
            }
        ],
    )
    # Same query, different max_results and casing/whitespace — must still hit
    # the normalized cache key.
    search_again = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c2",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query": "  Spain vs Saudi Arabia RESULT ", "max_results": 3}',
                },
            }
        ],
    )
    final = LLMResponse(content="Spain won 4-0.", tool_calls=[])
    exec_mock = MagicMock(
        return_value=ToolResult(
            tool_name="web_search",
            content="Spain 4-0 Saudi Arabia",
            is_error=False,
            call_id="c1",
        )
    )
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", exec_mock),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [search, search_again, final]
        run_agent("what was the score of Spain vs Saudi Arabia", selection, config=config)

    # The search actually ran only once; the near-duplicate was cached.
    assert exec_mock.call_count == 1
    third_turn_messages = client.chat.call_args_list[2].args[0]
    assert any(
        "Already retrieved earlier in this turn" in str(m.get("content", ""))
        for m in third_turn_messages
        if isinstance(m, dict)
    )


def test_read_cache_invalidated_after_mutation():
    # If a file is read, then written, a later read of the same path must run
    # again (the workspace changed), not be served from the stale cache.
    selection = default_selection("test:1b")
    # Large window so summarization (which consumes a mocked chat response) never
    # fires and shifts the scripted call sequence; this test is about cache
    # invalidation, not context management.
    selection.context_length = 1_000_000
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    read = LLMResponse(
        content="",
        tool_calls=[
            {"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "main.py"}'}}
        ],
    )
    write = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c2",
                "function": {
                    "name": "write_file",
                    "arguments": '{"path": "main.py", "content": "x=1"}',
                },
            }
        ],
    )
    read_again = LLMResponse(
        content="",
        tool_calls=[
            {"id": "c3", "function": {"name": "read_file", "arguments": '{"path": "main.py"}'}}
        ],
    )
    final = LLMResponse(content="Done.", tool_calls=[])

    def fake_execute(call, cfg):
        return ToolResult(
            tool_name=call.name,
            content="ok",
            is_error=False,
            call_id=call.call_id,
        )

    exec_mock = MagicMock(side_effect=fake_execute)
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", exec_mock),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [read, write, read_again, final]
        run_agent("edit main.py", selection, config=config)

    # read, write, AND the post-write read all executed: 3 real tool calls.
    assert exec_mock.call_count == 3


def test_final_round_forces_toolfree_wrapup():
    # A task that never finishes must not end on half-formed tool output. On the
    # last allowed round the loop disables tools and asks for a handoff summary.
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".", stream=False, auto_confirm=True, run_log_enabled=False, max_rounds=2
    )
    keep_calling = LLMResponse(
        content="",
        tool_calls=[{"id": "c1", "function": {"name": "ls", "arguments": '{"path": "."}'}}],
    )
    wrapup = LLMResponse(content="Done step 1; step 2 remains. Next: run tests.", tool_calls=[])

    exec_mock = MagicMock(
        side_effect=lambda call, _cfg: ToolResult(
            tool_name=call.name, content="a\nb", is_error=False, call_id=call.call_id
        )
    )
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", exec_mock),
    ):
        client = MockClient.return_value
        # Model would keep calling tools forever; the second call is the final round.
        client.chat.side_effect = [keep_calling, wrapup]
        result = run_agent("do a long multi-step task", selection, config=config)

    # The tool ran only on round 1; round 2 was forced tool-free.
    assert exec_mock.call_count == 1
    # Round 2 was called with tools disabled and carried the wrap-up directive.
    final_call = client.chat.call_args_list[1]
    assert final_call.kwargs.get("tools") is None
    sent = final_call.args[0]
    assert any("final step for this request" in str(m.get("content", "")) for m in sent)
    assert "step 2 remains" in result


def test_finish_blocked_while_todo_plan_has_open_steps(tmp_path):
    # The model plans with todo_write, does no real work, then tries to finish
    # while a step is still pending. The loop must push it back to the plan
    # instead of accepting a partial result — and accept the finish once the plan
    # is all completed.
    selection = default_selection("test:1b")
    selection.context_length = 1_000_000
    config = AgentConfig(cwd=str(tmp_path), stream=False, auto_confirm=True, run_log_enabled=False)
    plan = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "todo_write",
                    "arguments": '{"todos": [{"content": "do the real work", "status": "pending"}]}',
                },
            }
        ],
    )
    premature_finish = LLMResponse(content="All set!", tool_calls=[])
    complete_plan = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c2",
                "function": {
                    "name": "todo_write",
                    "arguments": '{"todos": [{"content": "do the real work", "status": "completed"}]}',
                },
            }
        ],
    )
    final = LLMResponse(content="Done — the work is complete.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [plan, premature_finish, complete_plan, final]
        result = run_agent("do a multi-step task", selection, config=config)

    # After the premature finish (round 2), round 3 must carry the continue nudge.
    third_turn_messages = client.chat.call_args_list[2].args[0]
    assert any(
        m.get("role") == "user" and "unfinished steps" in str(m.get("content", ""))
        for m in third_turn_messages
        if isinstance(m, dict)
    )
    # Once the plan is fully completed, the finish is accepted.
    assert "complete" in result.lower()


def test_finish_not_blocked_when_no_plan_was_created(tmp_path):
    # A task that never calls todo_write must finalize immediately — the guard is
    # run-scoped and must not read a stale todos.json from a prior run.
    (tmp_path / ".ci2lab").mkdir()
    (tmp_path / ".ci2lab" / "todos.json").write_text(
        '[{"id": "1", "content": "leftover", "status": "pending"}]',
        encoding="utf-8",
    )
    selection = default_selection("test:1b")
    selection.context_length = 1_000_000
    config = AgentConfig(cwd=str(tmp_path), stream=False, auto_confirm=True, run_log_enabled=False)
    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [LLMResponse(content="Here is the answer.", tool_calls=[])]
        result = run_agent("just answer a question", selection, config=config)

    assert client.chat.call_count == 1
    assert "answer" in result.lower()


def test_described_change_without_write_triggers_one_nudge():
    # The user asked to write code; the model only narrates it and never calls a
    # write tool. The loop nudges once to actually apply it, then accepts a real
    # write on the retry.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    prose = LLMResponse(content="Here is the code:\n\nprint('hi')", tool_calls=[])
    write = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "write_file",
                    "arguments": '{"path": "main.py", "content": "print(1)"}',
                },
            }
        ],
    )
    final = LLMResponse(content="Wrote main.py.", tool_calls=[])
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="write_file",
                content="Wrote main.py",
                is_error=False,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [prose, write, final]
        result = run_agent("write the python code into main.py", selection, config=config)

    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user" and "did not apply it" in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )
    assert "main.py" in result


def test_dependent_write_skipped_after_failed_read_in_same_round():
    # The model batches an optimistic plan in one turn: pdf_to_docx (fails) ->
    # read_document (fails) -> write_file with placeholder content. The write
    # depends on the failed steps, so it must be SKIPPED, never committing the
    # placeholder to disk.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    batched = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "pdf_to_docx",
                    "arguments": '{"source": "exam.pdf", "output": "exam.docx"}',
                },
            },
            {
                "id": "c2",
                "function": {"name": "read_document", "arguments": '{"path": "exam.docx"}'},
            },
            {
                "id": "c3",
                "function": {
                    "name": "write_file",
                    "arguments": '{"path": "ex1.txt", "content": "<EXERCISE_1_TEXT>"}',
                },
            },
        ],
    )
    final = LLMResponse(content="I could not read the PDF.", tool_calls=[])

    def fake_execute(call, _cfg):
        # Both upstream steps fail; the write must never reach execute_tool.
        return ToolResult(
            tool_name=call.name,
            content="Error: dependency missing" if call.name != "write_file" else "Wrote ex1.txt",
            is_error=call.name != "write_file",
            call_id=call.call_id,
        )

    exec_mock = MagicMock(side_effect=fake_execute)
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", exec_mock),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [batched, final]
        run_agent("read exam.pdf and write exercise 1 to a txt", selection, config=config)

    executed = [c.args[0].name for c in exec_mock.call_args_list]
    assert "write_file" not in executed  # placeholder write was skipped
    assert executed == ["pdf_to_docx", "read_document"]


def test_no_write_nudge_for_read_only_request():
    # A pure read/explain request must never get the "you didn't write" nudge.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    answer = LLMResponse(content="The loop lives in loop.py.", tool_calls=[])
    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.return_value = answer
        run_agent("explain where the agent loop is", selection, config=config)

    # Only one model round happened (no nudge-driven extra round).
    assert client.chat.call_count == 1


def test_run_agent_deletes_session_without_model_round(tmp_path, monkeypatch):
    from ci2lab.harness.session import save_session

    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    sid = "abc123"
    save_session(
        sid,
        messages=[{"role": "user", "content": "hello"}],
        model_tag="test:1b",
        cwd=str(tmp_path),
    )
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        session_id=sid,
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        result = run_agent(
            "delete what you just saved",
            selection,
            config=config,
        )

    assert "deleted" in result
    assert not (tmp_path / f"{sid}.json").exists()
    assert client.chat.call_count == 0


def test_run_agent_nudges_finalize_after_successful_edit(tmp_path):
    selection = default_selection("test:1b")
    target = tmp_path / "Tests.py"
    target.write_text("line three\n", encoding="utf-8")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        run_log_enabled=False,
    )

    edit_call = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "edit_file",
                    "arguments": (
                        '{"path": "Tests.py", "old_string": "line three", '
                        '"new_string": "Fourteenth attempt"}'
                    ),
                },
            }
        ],
    )
    final = LLMResponse(
        content="Done: line 3 of Tests.py now reads Fourteenth attempt.",
        tool_calls=[],
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [edit_call, final]
        result = run_agent(
            'change the third line of Tests.py to "Fourteenth attempt"',
            selection,
            config=config,
        )

    assert "Fourteenth attempt" in result
    assert client.chat.call_count == 2
    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user" and "applied successfully" in str(m.get("content", ""))
        for m in second_turn_messages
    )
    assert target.read_text(encoding="utf-8") == "Fourteenth attempt\n"


def test_fenced_mode_reinjects_tool_results_as_text_for_next_round(tmp_path):
    selection = default_selection("test:1b", tool_mode="fenced")
    selection.context_length = 1_000_000
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        run_log_enabled=False,
    )
    target = tmp_path / "notes" / "example.txt"
    write = LLMResponse(
        content=('```write_file\n{"path": "notes/example.txt", "content": "OK"}\n```'),
        tool_calls=[],
    )
    read = LLMResponse(
        content="```read_file\nnotes/example.txt\n```",
        tool_calls=[],
    )
    final = LLMResponse(
        content="Done. Tool used: write_file.",
        tool_calls=[],
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [write, read, final]
        result = run_agent("Create and verify the notes example file.", selection, config=config)

    assert "Tool used: write_file" in result
    assert target.read_text(encoding="utf-8") == "OK"
    second_round_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user"
        and "Tool results from the previous call" in str(m.get("content", ""))
        and "write_file result" in str(m.get("content", ""))
        and "OK" in str(m.get("content", ""))
        for m in second_round_messages
        if isinstance(m, dict)
    )


def test_stop_tools_phrase_forces_final_answer_without_executing_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    model_trying_tools = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query": "btc price", "max_results": 5}',
                },
            }
        ],
    )
    final = LLMResponse(
        content="With what I have, I can't verify the full source. Warning: partial data.",
        tool_calls=[],
    )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool") as mock_execute_tool,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [model_trying_tools, final]
        result = run_agent(
            "bitcoin price now, answer with what you know and stop searching",
            selection,
            config=config,
        )

    assert "warning" in result.lower()
    assert mock_execute_tool.call_count == 0


def test_run_agent_disables_streaming_when_tools_are_available():
    selection = default_selection("test:1b")
    selection.supports_tools = True
    config = AgentConfig(cwd=".", stream=True, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query": "btc price", "max_results": 5}',
                },
            }
        ],
    )
    final = LLMResponse(content="Final answer with results.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.call_llm") as mock_call_llm:
        mock_call_llm.side_effect = [with_tool, final]
        run_agent("tell me the current bitcoin price", selection, config=config)

    first_call = mock_call_llm.call_args_list[0]
    assert first_call.kwargs["stream"] is False


def test_governor_stops_on_repeated_error_class_with_varying_args():
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        run_log_enabled=False,
    )

    def docx_call(n):
        return LLMResponse(
            content="",
            tool_calls=[
                {
                    "id": f"c{n}",
                    "function": {
                        "name": "docx_to_pdf",
                        "arguments": f'{{"source": "a.docx", "output": "out{n}.pdf"}}',
                    },
                }
            ],
        )

    final = LLMResponse(content="done", tool_calls=[])
    dispatched: list[str] = []

    def fake_execute_tool(call, _cfg):
        dispatched.append(call.name)
        return ToolResult(
            tool_name=call.name,
            content="Error: could not create out.pdf: a valid PDF engine is missing.",
            is_error=True,
            call_id=call.call_id,
            outcome="failed",
        )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute_tool),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [docx_call(1), docx_call(2), docx_call(3), docx_call(4), final]
        result = run_agent("convert a.docx to pdf", selection, config=config)

    # Stopped by the governor after the same error class repeated, not after the
    # full round budget. Varying output paths keep the signature detector quiet,
    # so this exercises the governor specifically.
    assert "kept failing" in result
    assert len(dispatched) == 3
    assert client.chat.call_count == 3


def test_has_write_intent_ignores_negated_write_verbs():
    from ci2lab.harness.query.loop import _has_write_intent

    # A prohibition is not a request to write.
    assert _has_write_intent("Report the error code. Do not modify any files.") is False
    assert _has_write_intent("Trace the flag across files. Don't edit anything.") is False
    # A real write request keeps its intent even next to a prohibition.
    assert _has_write_intent("Fix the root cause. Do not edit any test file.") is True
    assert _has_write_intent("Implement parse_duration in durations.py.") is True
    assert _has_write_intent("hola") is False


def test_references_workspace_detects_local_signals():
    from ci2lab.harness.query.loop import _references_workspace

    assert _references_workspace("Find the fatal code in app.log") is True
    assert _references_workspace("In this Python project, which function returns it?") is True
    assert _references_workspace("Run `bash build.sh` and tell me the exit code") is True
    assert _references_workspace("Trace how the --threshold flag reaches the code") is True
    assert _references_workspace("hola, ¿qué tal?") is False
    assert _references_workspace("What is a monad?") is False


def test_agent_can_write_files_respects_write_tools_disabled():
    # Configuration-level write disablement means "cannot write", regardless of
    # the allow-list: the executor is guaranteed to block those tools, so no
    # nudge may steer the model toward them.
    assert _agent_can_write_files(AgentConfig(cwd=".", write_tools_enabled=False)) is False


def test_workspace_answer_with_zero_tool_attempts_gets_grounding_nudge():
    # The user asks about this project; the model answers from memory without a
    # single tool call. The loop nudges once toward real evidence, then accepts
    # the follow-up answer (bounded so it can never trap the model).
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )
    guess = LLMResponse(content="The discount function is get_discount.", tool_calls=[])
    final = LLMResponse(content="I checked and it is get_discount.", tool_calls=[])
    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [guess, final]
        result = run_agent(
            "In this Python project, which function computes the shipping discount? "
            "Do not modify any files.",
            selection,
            config=config,
        )

    assert client.chat.call_count == 2
    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user" and "do not answer from memory" in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )
    assert result == "I checked and it is get_discount."


def test_plain_conversation_is_not_nudged_for_grounding():
    # A conversational turn with no workspace reference finishes in one round;
    # the grounding gate must not tax ordinary chat with extra rounds.
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    reply = LLMResponse(content="¡Hola! Todo bien por aquí.", tool_calls=[])
    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.return_value = reply
        result = run_agent("hola, ¿qué tal?", selection, config=config)

    assert client.chat.call_count == 1
    assert "Hola" in result


def test_grounding_nudge_skipped_when_tools_were_attempted():
    # The model tried a tool, it failed, and the model honestly reports the
    # blocker. That answer is grounded in the real attempt — it must be
    # accepted, not sent back to dig for more evidence it cannot get.
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )
    attempt = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c1",
                "function": {"name": "read_file", "arguments": '{"path": "app.log"}'},
            }
        ],
    )
    report = LLMResponse(content="I could not read app.log: access denied.", tool_calls=[])
    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch(
            "ci2lab.harness.query.loop.execute_tool",
            return_value=ToolResult(
                tool_name="read_file",
                content="Error: access denied",
                is_error=True,
                call_id="c1",
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [attempt, report]
        result = run_agent("Report the fatal error code from app.log.", selection, config=config)

    assert client.chat.call_count == 2
    assert "could not read" in result


def test_write_disabled_prose_answer_gets_grounding_nudge_not_write_nudge():
    # Writes are disabled by configuration, so the "apply the change" nudge must
    # stay silent (its tool would be blocked); the grounding gate still pushes
    # the zero-attempt answer toward read-only evidence, once.
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        write_tools_enabled=False,
        verify_final_answer=False,
    )
    prose = LLMResponse(content="Change line 3 of the config to solve it.", tool_calls=[])
    final = LLMResponse(content="Based on the file, line 3 is the culprit.", tool_calls=[])
    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [prose, final]
        run_agent("Fix the bug in config.py.", selection, config=config)

    assert client.chat.call_count == 2
    second_turn_messages = client.chat.call_args_list[1].args[0]
    joined = " ".join(
        str(m.get("content", "")) for m in second_turn_messages if isinstance(m, dict)
    )
    assert "did not apply it" not in joined
    assert "do not answer from memory" in joined


def test_red_check_can_be_rerun_after_a_fix():
    # Red test (twice) -> apply a fix -> re-run the SAME test command. The
    # exact-repeat failure guard must not block the re-run: a successful
    # mutation resets failure counts because the workspace changed. Without the
    # reset, the third pytest run would be short-circuited by MAX_SAME_CALL.
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=".",
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
        verify_final_answer=False,
    )

    def bash_call(call_id: str) -> LLMResponse:
        return LLMResponse(
            content="",
            tool_calls=[
                {
                    "id": call_id,
                    "function": {
                        "name": "bash",
                        "arguments": '{"command": "python -m pytest -q"}',
                    },
                }
            ],
        )

    def read_call(call_id: str, path: str) -> dict:
        return {
            "id": call_id,
            "function": {"name": "read_file", "arguments": f'{{"path": "{path}"}}'},
        }

    # Round 1: red test + read a file (different signatures per round so the
    # round-level loop detector stays quiet and the exact-call governor is the
    # mechanism under test).
    red1 = LLMResponse(
        content="",
        tool_calls=[bash_call("c1").tool_calls[0], read_call("r1", "m.py")],
    )
    red2 = LLMResponse(
        content="",
        tool_calls=[bash_call("c2").tool_calls[0], read_call("r2", "test_m.py")],
    )
    fix = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c3",
                "function": {
                    "name": "edit_file",
                    "arguments": '{"path": "m.py", "old_string": "a", "new_string": "b"}',
                },
            }
        ],
    )
    rerun = bash_call("c4")
    final = LLMResponse(content="Fixed; the test passes now.", tool_calls=[])

    executed: list[str] = []

    def fake_execute_tool(call, _cfg):
        executed.append(call.name)
        if call.name == "bash":
            if executed.count("bash") <= 2:
                return ToolResult(
                    tool_name="bash",
                    content="Error: command exited with code 1.\n1 failed\n[exit code 1]",
                    is_error=True,
                    call_id=call.call_id,
                    outcome="command_failed",
                )
            return ToolResult(
                tool_name="bash", content="1 passed", is_error=False, call_id=call.call_id
            )
        if call.name == "read_file":
            return ToolResult(
                tool_name="read_file", content="def f(): ...", is_error=False, call_id=call.call_id
            )
        return ToolResult(
            tool_name="edit_file",
            content="Edited m.py: 1 replacement(s)",
            is_error=False,
            call_id=call.call_id,
        )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute_tool),
        # Keep compaction inert: its LLM-summary path shares the mocked client
        # and would otherwise consume the scripted responses mid-run.
        patch(
            "ci2lab.harness.query.loop.manage_context",
            side_effect=lambda history, client, context_length, summary_failures=0: (
                history,
                summary_failures,
                [],
            ),
        ),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [red1, red2, fix, rerun, final]
        result = run_agent("fix the failing test in m.py", selection, config=config)

    # The re-run after the fix really executed (3 bash runs), and the run ended
    # normally instead of being cut off by the error-class limit.
    assert executed.count("bash") == 3
    assert "passes" in result
