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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
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

    with patch("ci2lab.harness.loop.LLMClient") as MockClient:
        client = MockClient.return_value
        client.chat.side_effect = [refusal, refusal]
        result = run_agent("resume prueba.md", selection, config=config)

    assert "ideas principales" in result.lower()
    assert "informal" in result.lower()
    assert "formal" in result.lower()
    assert client.chat.call_count == 0
