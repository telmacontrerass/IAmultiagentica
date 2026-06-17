from unittest.mock import MagicMock, patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.token_usage import TokenUsage
from ci2lab.harness.query.loop import _prepend_missing_reads
from ci2lab.harness.types import ToolCall, ToolResult


def test_run_agent_single_turn_no_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    mock_response = LLMResponse(content="Listo, aquí está el resumen.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = mock_response
        result = run_agent("resume el proyecto", selection, config=config)

    assert "resumen" in result.lower()


def test_run_agent_accumulates_token_usage_across_rounds():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "ls", "arguments": '{"path": "."}'},
        }],
        usage=TokenUsage(
            prompt_tokens=10,
            completion_tokens=3,
            total_tokens=13,
            model="test:1b",
        ),
    )
    final = LLMResponse(
        content="Hay varios archivos.",
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
        run_agent("lista archivos", selection, config=config)

    assert config.token_usage.turn.prompt_tokens == 30
    assert config.token_usage.turn.completion_tokens == 7
    assert config.token_usage.turn.total_tokens == 37
    assert config.token_usage.session.total_tokens == 37


def test_run_agent_executes_tool_then_answers():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "ls", "arguments": '{"path": "."}'},
        }],
    )
    final = LLMResponse(content="Hay varios archivos.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        result = run_agent("lista archivos", selection, config=config)

    assert "archivos" in result.lower()
    assert client.chat.call_count == 2


def test_run_agent_stream_true_prints_final_text_when_not_streamed():
    selection = default_selection("test:1b")
    selection.supports_tools = True
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    final = LLMResponse(content="hola mundo", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.call_llm", return_value=final),
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        result = run_agent("Responde exactamente: hola mundo", selection, config=config)

    assert result == "hola mundo"
    printed_texts = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    assert any("hola mundo" in text for text in printed_texts)


def test_run_agent_prints_model_text_before_tool_execution():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="I will inspect the workspace first.",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "ls", "arguments": '{"path": "."}'},
        }],
    )
    final = LLMResponse(content="Hay varios archivos.", tool_calls=[])

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        run_agent("lista archivos", selection, config=config)

    printed_texts = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    assert any("Modelo:" in text and "inspect the workspace" in text for text in printed_texts)


def test_run_agent_nudges_web_search_once_after_no_internet_reply():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    first = LLMResponse(
        content="No tengo acceso a internet en tiempo real ahora mismo.",
        tool_calls=[],
    )
    second = LLMResponse(content="Perfecto, usaré web_search.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [first, second]
        result = run_agent("dime un resultado live", selection, config=config)

    assert "usaré web_search" in result.lower() or "usare web_search" in result.lower()
    assert client.chat.call_count == 2
    second_turn_messages = client.chat.call_args_list[1].args[0]
    nudge_messages = [
        m.get("content", "")
        for m in second_turn_messages
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    assert sum(
        "You can use `web_search` for live info without a URL" in str(msg)
        for msg in nudge_messages
    ) == 1


def test_run_agent_does_not_reuse_false_success_text_before_tool_result():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="Result: Command executed successfully. Removed archivo.txt.",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "bash", "arguments": '{"command": "rm archivo.txt"}'},
        }],
    )
    final = LLMResponse(content="La acción fue bloqueada por política de seguridad.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        result = run_agent("borra archivo.txt", selection, config=config)

    assert "bloquead" in result.lower()
    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert not any(
        "executed successfully" in str(m.get("content", "")).lower()
        or "removed archivo.txt" in str(m.get("content", "")).lower()
        for m in second_turn_messages
        if isinstance(m, dict)
    )


def test_run_agent_loop_break_nudge_restates_original_prompt():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    original = "tell me the score of spains soccer match from yesterday"
    repeated_call = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "ls", "arguments": '{"path": "."}'},
        }],
    )
    final = LLMResponse(content="No hay marcador en los resultados disponibles.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [repeated_call, repeated_call, repeated_call, final]
        run_agent(original, selection, config=config)

    fourth_round_messages = client.chat.call_args_list[3].args[0]
    assert any(
        m.get("role") == "user"
        and "Petición original:" in str(m.get("content", ""))
        and original in str(m.get("content", ""))
        for m in fourth_round_messages
    )


def test_run_agent_forces_docx_conversion_after_repeated_discovery(tmp_path, monkeypatch):
    selection = default_selection("test:1b")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        run_log_enabled=False,
    )
    prueba = tmp_path / "Prueba"
    prueba.mkdir()
    (prueba / "piramides_egipto.docx").write_bytes(b"fake docx")
    converted: dict[str, str] = {}

    def fake_docx_to_pdf(cwd: str, source: str, output: str) -> str:
        converted["cwd"] = cwd
        converted["source"] = source
        converted["output"] = output
        return f"Creado {output} desde {source}"

    monkeypatch.setattr(
        "ci2lab.harness.tools.convert.docx_to_pdf",
        fake_docx_to_pdf,
    )

    repeated_discovery = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "ls", "arguments": '{"path": "Prueba"}'},
        }],
    )
    final = LLMResponse(content="Convertido a PDF.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [repeated_discovery, repeated_discovery, final]
        result = run_agent(
            "inside the Prueba folder, find the docx file and convert it to pdf",
            selection,
            config=config,
        )

    assert "Convertido" in result
    assert converted["source"] == "Prueba/piramides_egipto.docx"
    assert converted["output"] == "Prueba/piramides_egipto.pdf"
    assert client.chat.call_count == 3


def test_run_agent_reads_exact_pdf_request_without_model_round(tmp_path, monkeypatch):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "prueba.pdf").write_text("fake pdf", encoding="utf-8")
    monkeypatch.setattr(
        "ci2lab.harness.tools.filesystem.extract_pdf_text",
        lambda _path: "[PDF page 1/1]\nEl PDF trata sobre registro formal e informal.",
    )
    monkeypatch.setattr(
        "ci2lab.harness.tools.filesystem._pdf_section_count",
        lambda _path: "1 paginas",
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        result = run_agent("resume el pdf prueba.pdf", selection, config=config)

    assert "registro formal" in result.lower()
    assert client.chat.call_count == 0


def test_run_agent_resolves_natural_pdf_reference(tmp_path, monkeypatch):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "prueba.pdf").write_text("fake pdf", encoding="utf-8")
    monkeypatch.setattr(
        "ci2lab.harness.tools.filesystem.extract_pdf_text",
        lambda _path: "[PDF page 1/1]\nEl PDF trata sobre registro formal e informal.",
    )
    monkeypatch.setattr(
        "ci2lab.harness.tools.filesystem._pdf_section_count",
        lambda _path: "1 paginas",
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        result = run_agent("resume el contenido del pdf de prueba", selection, config=config)

    assert "registro formal" in result.lower()
    assert client.chat.call_count == 0


def test_run_agent_asks_for_document_name_when_reference_is_ambiguous(tmp_path):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "uno.pdf").write_text("fake pdf", encoding="utf-8")
    (tmp_path / "dos.pdf").write_text("fake pdf", encoding="utf-8")

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        result = run_agent("resume el contenido del pdf", selection, config=config)

    assert "qué documento" in result.lower() or "que documento" in result.lower()
    assert "uno.pdf" in result
    assert "dos.pdf" in result
    assert client.chat.call_count == 0


def test_run_agent_answers_simple_document_summary_without_extra_model_round(tmp_path):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "prueba.md").write_text(
        "# Registro formal e informal\n\n"
        "El documento explica que la escritura informal usa contracciones, "
        "abreviaturas y verbos frasales.\n"
        "La escritura academica formal usa voz pasiva, tono impersonal y "
        "vocabulario mas preciso.\n",
        encoding="utf-8",
    )

    refusal = LLMResponse(
        content="No puedo acceder a archivos locales.",
        tool_calls=[],
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [refusal, refusal]
        result = run_agent("resume prueba.md", selection, config=config)

    assert "ideas principales" in result.lower()
    assert "informal" in result.lower()
    assert "formal" in result.lower()
    assert client.chat.call_count == 0


def test_prepend_missing_reads_before_edit():
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "Pruebas.py",
                "old_string": "a",
                "new_string": "b",
            },
        )
    ]
    result = _prepend_missing_reads(
        calls,
        "First read Pruebas.py, then change line 3",
    )
    assert len(result) == 2
    assert result[0].name == "read_file"
    assert result[0].arguments["path"] == "Pruebas.py"
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
    assert "no vacio" in result.content.lower()


def test_local_repo_question_uses_tree_or_ls_not_empty_bash():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    first = LLMResponse(
        content='tree\n{"path": ".", "depth": 2, "max_entries": 100}',
        tool_calls=[],
    )
    final = LLMResponse(
        content=(
            "Archivos principales: README.md, pyproject.toml, ci2lab/, tests/. "
            "El loop del agente parece estar en ci2lab/harness/query/loop.py."
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
            "Lista los archivos principales del repositorio y dime en qué carpeta parece estar el loop del agente.",
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
        "Lista los archivos principales del repositorio y dime en qué carpeta "
        "parece estar el loop del agente."
    )
    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "tree", "arguments": '{"path": ".", "depth": 2, "max_entries": 100}'},
        }],
    )
    final = LLMResponse(content="El loop parece estar en ci2lab/harness/query/loop.py.", tool_calls=[])

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
        and "La peticion actual del usuario es:" in str(m.get("content", ""))
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
        tool_calls=[{
            "id": "c1",
            "function": {"name": "tree", "arguments": '{"path": ".", "depth": 2, "max_entries": 100}'},
        }],
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
        and "La peticion actual del usuario es:" in str(m.get("content", ""))
        and prompt in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )


def test_classic_loop_has_no_role_anchor_by_default():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "tree", "arguments": '{"path": ".", "depth": 2, "max_entries": 100}'},
        }],
    )
    final = LLMResponse(content="The loop seems to be in ci2lab/harness/query/loop.py.", tool_calls=[])

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
        m.get("role") == "user"
        and "Role anchor:" in str(m.get("content", ""))
        for m in second_turn_messages
        if isinstance(m, dict)
    )


def test_context_summary_does_not_override_current_user_request():
    selection = default_selection("test:1b")
    selection.context_length = 8192
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    prompt = (
        "Lista los archivos principales del repositorio y dime en qué carpeta "
        "parece estar el loop del agente."
    )
    old_messages = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "Tarea antigua: crea docs/resumen.md"},
        {"role": "assistant", "content": "Voy a crear docs/resumen.md"},
    ]
    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "tree", "arguments": '{"path": ".", "depth": 2, "max_entries": 100}'},
        }],
    )
    final = LLMResponse(content="El loop parece estar en ci2lab/harness/query/loop.py.", tool_calls=[])
    manage_calls = {"count": 0}

    def fake_manage_context(history, client, context_length, summary_failures=0):
        manage_calls["count"] += 1
        if manage_calls["count"] == 2:
            injected = list(history)
            injected.insert(
                1,
                {
                    "role": "user",
                    "content": "[Summary of earlier conversation]\n\nLa tarea era crear docs/resumen.md",
                },
            )
            return injected, summary_failures, ["Contexto: historial resumido (~1000 → ~500 tokens estimados)."]
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
        and "La peticion actual del usuario es:" in str(m.get("content", ""))
        and prompt in str(m.get("content", ""))
        for m in second_turn_messages
    )


def test_run_agent_deletes_session_without_model_round(tmp_path, monkeypatch):
    from ci2lab.harness.session import save_session

    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    sid = "abc123"
    save_session(
        sid,
        messages=[{"role": "user", "content": "hola"}],
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
            "elimina lo que acabas de guardar",
            selection,
            config=config,
        )

    assert "eliminada" in result
    assert not (tmp_path / f"{sid}.json").exists()
    assert client.chat.call_count == 0


def test_run_agent_nudges_finalize_after_successful_edit(tmp_path):
    selection = default_selection("test:1b")
    target = tmp_path / "Pruebas.py"
    target.write_text("linea tres\n", encoding="utf-8")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        require_diff_preview=False,
        run_log_enabled=False,
    )

    edit_call = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {
                "name": "edit_file",
                "arguments": (
                    '{"path": "Pruebas.py", "old_string": "linea tres", '
                    '"new_string": "Decimocuarto intento"}'
                ),
            },
        }],
    )
    final = LLMResponse(
        content="Listo: la línea 3 de Pruebas.py ahora dice Decimocuarto intento.",
        tool_calls=[],
    )

    with patch("ci2lab.harness.query.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [edit_call, final]
        result = run_agent(
            'change the third line of Pruebas.py to "Decimocuarto intento"',
            selection,
            config=config,
        )

    assert "Decimocuarto intento" in result
    assert client.chat.call_count == 2
    second_turn_messages = client.chat.call_args_list[1].args[0]
    assert any(
        m.get("role") == "user" and "se aplicó correctamente" in str(m.get("content", ""))
        for m in second_turn_messages
    )
    assert target.read_text(encoding="utf-8") == "Decimocuarto intento\n"


def test_web_fetch_403_fallback_blocks_repeat_filesystem_and_placeholder_mcp():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    q = "precio actual bitcoin usd"
    round1 = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "web_search", "arguments": f'{{"query": "{q}", "max_results": 5}}'},
        }],
    )
    round2 = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c2",
            "function": {
                "name": "web_fetch",
                "arguments": '{"url": "https://www.coinbase.com/en-es/converter/btc/usd"}',
            },
        }],
    )
    round3 = LLMResponse(
        content="",
        tool_calls=[
            {
                "id": "c3",
                "function": {"name": "web_search", "arguments": f'{{"query": "{q}", "max_results": 5}}'},
            },
            {
                "id": "c4",
                "function": {
                    "name": "mcp_call",
                    "arguments": '{"server": "MCP_SERVER_NAME", "tool": "search", "arguments": {}}',
                },
            },
            {
                "id": "c5",
                "function": {"name": "ls", "arguments": '{"path": "."}'},
            },
        ],
    )
    final = LLMResponse(
        content=(
            "El precio exacto no pudo verificarse en una fuente completa por bloqueo HTTP 403.\n"
            "Advertencia: respondo con snippets ya disponibles."
        ),
        tool_calls=[],
    )

    executed_calls: list[str] = []

    def fake_execute_tool(call, _cfg):
        executed_calls.append(call.name)
        if call.name == "web_search":
            return ToolResult(
                tool_name="web_search",
                content="Snippet: BTC price around 106k USD from search results.",
                is_error=False,
                call_id=call.call_id,
            )
        if call.name == "web_fetch":
            return ToolResult(
                tool_name="web_fetch",
                content="HTTP 403 Forbidden",
                is_error=True,
                call_id=call.call_id,
            )
        raise AssertionError(f"Unexpected tool call executed: {call.name}")

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute_tool),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [round1, round2, round3, final]
        result = run_agent("dime el precio actual de bitcoin", selection, config=config)

    assert "advertencia" in result.lower()
    assert executed_calls == ["web_search", "web_fetch"]
    assert client.chat.call_count == 4
    fourth_round_messages = client.chat.call_args_list[3].args[0]
    assert any(
        "no repitas la misma búsqueda" in str(m.get("content", "")).lower()
        for m in fourth_round_messages
        if isinstance(m, dict) and m.get("role") == "user"
    )


def test_stop_tools_phrase_forces_final_answer_without_executing_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    model_trying_tools = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "web_search", "arguments": '{"query": "btc price", "max_results": 5}'},
        }],
    )
    final = LLMResponse(
        content="Con lo disponible, no puedo verificar la fuente completa. Advertencia: datos parciales.",
        tool_calls=[],
    )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool") as mock_execute_tool,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [model_trying_tools, final]
        result = run_agent(
            "precio bitcoin ahora, responde con lo que sabes y no sigas buscando",
            selection,
            config=config,
        )

    assert "advertencia" in result.lower()
    assert mock_execute_tool.call_count == 0


def test_factual_web_flow_blocks_duplicate_search_and_hides_pretool_hallucination():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    query = "precio bitcoin usd actual"

    round1 = LLMResponse(
        content="El precio actual es 200000 USD.\n```web_search\n{\"query\": \"precio bitcoin usd actual\", \"max_results\": 5}\n```",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "web_search", "arguments": f'{{"query": "{query}", "max_results": 5}}'},
        }],
    )
    round2 = LLMResponse(
        content="Repito búsqueda.\n```web_search\n{\"query\": \"precio bitcoin usd actual\", \"max_results\": 5}\n```",
        tool_calls=[{
            "id": "c2",
            "function": {"name": "web_search", "arguments": f'{{"query": "{query}", "max_results": 5}}'},
        }],
    )
    final = LLMResponse(
        content=(
            "Con los resultados disponibles, BTC ronda 106k USD.\n"
            "Advertencia: no pude verificar una fuente completa adicional."
        ),
        tool_calls=[],
    )

    executed_calls: list[str] = []

    def fake_execute_tool(call, _cfg):
        executed_calls.append(call.name)
        return ToolResult(
            tool_name="web_search",
            content="Snippet: BTC near 106k USD.",
            is_error=False,
            call_id=call.call_id,
        )

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute_tool),
        patch("ci2lab.harness.query.loop.console.print") as mock_print,
    ):
        client = MockClient.return_value
        client.chat.side_effect = [round1, round2, final]
        result = run_agent("Dime el precio del bitcoin actual", selection, config=config)

    assert executed_calls == ["web_search"]
    assert "advertencia" in result.lower()
    assert "200000" not in result
    printed = [str(c.args[0]) for c in mock_print.call_args_list if c.args]
    assert not any("200000" in text for text in printed)
    assert client.chat.call_count == 3


def test_run_agent_disables_streaming_when_tools_are_available():
    selection = default_selection("test:1b")
    selection.supports_tools = True
    config = AgentConfig(cwd=".", stream=True, auto_confirm=True, run_log_enabled=False)

    with_tool = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {"name": "web_search", "arguments": '{"query": "btc price", "max_results": 5}'},
        }],
    )
    final = LLMResponse(content="Respuesta final con resultados.", tool_calls=[])

    with patch("ci2lab.harness.query.loop.call_llm") as mock_call_llm:
        mock_call_llm.side_effect = [with_tool, final]
        run_agent("dime el precio del bitcoin actual", selection, config=config)

    first_call = mock_call_llm.call_args_list[0]
    assert first_call.kwargs["stream"] is False


def test_web_fetch_round_reanchors_bitcoin_price_question_and_avoids_supply_drift():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)
    prompt = (
        "Dime el precio actual del bitcoin usando internet. "
        "No respondas solo con resultados de búsqueda: primero busca una fuente "
        "y luego intenta leer la página con web_fetch."
    )

    search_round = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c1",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "precio de Bitcoin actual", "max_results": 1}',
            },
        }],
    )
    fetch_round = LLMResponse(
        content="",
        tool_calls=[{
            "id": "c2",
            "function": {
                "name": "web_fetch",
                "arguments": '{"url": "https://coinmarketcap.com/es/currencies/bitcoin/"}',
            },
        }],
    )
    drift_final = LLMResponse(
        content="Actualmente hay alrededor de 19.7 millones de Bitcoin en circulación.",
        tool_calls=[],
    )
    corrected_final = LLMResponse(
        content="El precio ronda 106,000 USD. Advertencia: cifra aproximada según la fuente leída.",
        tool_calls=[],
    )

    def fake_execute_tool(call, _cfg):
        if call.name == "web_search":
            return ToolResult(
                tool_name="web_search",
                content="1. CoinMarketCap https://coinmarketcap.com/es/currencies/bitcoin/",
                is_error=False,
                call_id=call.call_id,
            )
        if call.name == "web_fetch":
            return ToolResult(
                tool_name="web_fetch",
                content=(
                    "Fetched https://coinmarketcap.com/es/currencies/bitcoin/ [200]\n\n"
                    "Bitcoin price today is $106,123.45 USD. Market cap ... "
                    "Circulating supply is 19.7M BTC."
                ),
                is_error=False,
                call_id=call.call_id,
            )
        raise AssertionError(f"Unexpected tool {call.name}")

    with (
        patch("ci2lab.harness.query.loop.LLMClient") as MockClient,
        patch("ci2lab.harness.query.loop.execute_tool", side_effect=fake_execute_tool),
    ):
        client = MockClient.return_value
        client.chat.side_effect = [search_round, fetch_round, drift_final, corrected_final]
        result = run_agent(prompt, selection, config=config)

    assert "precio" in result.lower() or "usd" in result.lower()
    assert "circulación" not in result.lower()
    assert client.chat.call_count == 4
    fourth_round_messages = client.chat.call_args_list[3].args[0]
    assert any(
        "pregunta original del usuario" in str(m.get("content", "")).lower()
        for m in fourth_round_messages
        if isinstance(m, dict) and m.get("role") == "user"
    )
