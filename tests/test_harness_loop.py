from unittest.mock import MagicMock, patch

from ci2lab.harness import AgentConfig, default_selection, run_agent
from ci2lab.harness.llm_client import LLMResponse


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
