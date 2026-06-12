from unittest.mock import MagicMock, patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse
from ci2lab.harness.loop import _prepend_missing_reads
from ci2lab.harness.types import ToolCall


def test_run_agent_single_turn_no_tools():
    selection = default_selection("test:1b")
    config = AgentConfig(cwd=".", stream=False, auto_confirm=True, run_log_enabled=False)

    mock_response = LLMResponse(content="Listo, aquí está el resumen.", tool_calls=[])

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = mock_response
        result = run_agent("resume el proyecto", selection, config=config)

    assert "resumen" in result.lower()


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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [with_tool, final]
        result = run_agent("lista archivos", selection, config=config)

    assert "archivos" in result.lower()
    assert client.chat.call_count == 2


def test_run_agent_retries_pdf_request_when_model_refuses_tools(tmp_path):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "prueba.pdf").write_text("fake pdf", encoding="utf-8")

    refusal = LLMResponse(
        content=(
            "Lo siento, pero no puedo acceder a archivos externos. "
            "Puedes usar `read_file`."
        ),
        tool_calls=[],
    )
    with_tool = LLMResponse(
        content="```read_file\nprueba.pdf\n```",
        tool_calls=[],
    )
    final = LLMResponse(content="El PDF trata sobre registro formal.", tool_calls=[])

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [refusal, with_tool, final]
        result = run_agent("resume el pdf prueba.pdf", selection, config=config)

    assert "registro formal" in result.lower()
    assert client.chat.call_count == 3


def test_run_agent_retries_pdf_request_when_model_hallucinates_success(tmp_path):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "prueba.pdf").write_text("fake pdf", encoding="utf-8")

    hallucinated = LLMResponse(
        content="The PDF 'prueba.pdf' has been successfully resumed.",
        tool_calls=[],
    )
    with_tool = LLMResponse(
        content="```read_file\nprueba.pdf\n```",
        tool_calls=[],
    )
    final = LLMResponse(content="El PDF trata sobre registro formal.", tool_calls=[])

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [hallucinated, with_tool, final]
        result = run_agent("resume el pdf prueba.pdf", selection, config=config)

    assert "registro formal" in result.lower()
    assert client.chat.call_count == 3


def test_run_agent_auto_reads_pdf_when_model_never_calls_tool(tmp_path):
    selection = default_selection("test:1b", tool_mode="fenced")
    config = AgentConfig(
        cwd=str(tmp_path),
        stream=False,
        auto_confirm=True,
        run_log_enabled=False,
    )
    (tmp_path / "prueba.pdf").write_text("fake pdf", encoding="utf-8")

    refusal = LLMResponse(
        content="Lo siento, pero no puedo acceder a archivos externos.",
        tool_calls=[],
    )
    final = LLMResponse(content="El PDF trata sobre registro formal.", tool_calls=[])

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [refusal, refusal, final]
        result = run_agent("resume el pdf prueba.pdf", selection, config=config)

    assert "registro formal" in result.lower()
    assert client.chat.call_count == 3


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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [refusal, refusal]
        result = run_agent("resume prueba.md", selection, config=config)

    assert "ideas principales" in result.lower()
    assert "informal" in result.lower()
    assert "formal" in result.lower()
    assert client.chat.call_count == 2


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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
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
