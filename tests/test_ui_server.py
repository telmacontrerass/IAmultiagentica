import base64

from ci2lab.config import Ci2LabConfig
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMModelNotFoundError
from ci2lab.harness.session import load_session, save_session
from ci2lab.harness.token_usage import TokenUsage
from ci2lab.hardware.profile import build_cpu_profile_for_testing
from ci2lab.ui.server import (
    UIState,
    _chat,
    _chat_start,
    _content_type,
    _delete_session_payload,
    _delete_task_payload,
    _finish_delete_task,
    _health_payload,
    _pull_task_payload,
    _prompt_with_uploaded_files,
    _record_pull_event,
    _session_payload,
    _sessions_payload,
    _system_payload,
    _tools_payload,
    _upload_file,
)


def test_content_type_for_static_assets():
    assert _content_type("index.html").startswith("text/html")
    assert _content_type("styles.css").startswith("text/css")
    assert _content_type("app.js").startswith("application/javascript")


def test_health_payload_reports_local_only(monkeypatch):
    state = UIState(runtime=Ci2LabConfig())
    monkeypatch.setattr(state, "list_installed_models", lambda: ([{"name": "m:1"}], None))

    payload = _health_payload(state)

    assert payload["ok"] is True
    assert payload["installed_count"] == 1
    assert payload["local_only"] is True


def test_chat_start_payload_reports_terminal_like_context(tmp_path, monkeypatch):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path), model="qwen2.5-coder:1.5b"))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="qwen2.5-coder-1.5b",
            ollama_tag="qwen2.5-coder:1.5b",
            display_name="Qwen2.5 Coder 1.5B",
            tool_mode="fenced",
        )

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)

    payload = _chat_start(
        state,
        {"model": "qwen2.5-coder-1.5b"},
    )

    assert payload["ok"] is True
    assert payload["model"] == "qwen2.5-coder:1.5b"
    assert payload["tool_mode"] == "fenced"
    assert payload["cwd"] == str(tmp_path)
    assert payload["session_id"]
    assert payload["ui_mode"] == "herramientas_activas"
    assert payload["multi_agent"] is False


def test_chat_start_reports_multi_agent_mode(tmp_path, monkeypatch):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path), model="qwen2.5-coder:1.5b"))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="qwen2.5-coder-1.5b",
            ollama_tag="qwen2.5-coder:1.5b",
            display_name="Qwen2.5 Coder 1.5B",
            tool_mode="fenced",
        )

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)

    payload = _chat_start(
        state,
        {"multi_agent": True, "model": "qwen2.5-coder-1.5b"},
    )

    assert payload["ok"] is True
    assert payload["multi_agent"] is True
    assert payload["ui_mode"] == "multi_agent"
    assert payload["security_profile"] == state.runtime.security.profile


def test_chat_returns_llm_error_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    state = UIState(runtime=Ci2LabConfig())
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "missing:1b"}], None),
    )

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="missing-1b",
            ollama_tag="missing:1b",
            display_name="missing:1b",
        )

    def fake_run_agent(*args, **kwargs):
        raise LLMModelNotFoundError("missing:1b")

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)
    monkeypatch.setattr("ci2lab.ui.server.run_agent", fake_run_agent)

    payload = _chat(state, {"message": "hola", "model": "missing:1b"})

    assert payload["ok"] is False
    assert "missing:1b" in payload["error"]
    assert payload["session_id"]


def test_chat_saves_pending_session_when_model_setup_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    state = UIState(runtime=Ci2LabConfig())
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "missing:1b"}], None),
    )

    def fail_prepare_session(*args, **kwargs):
        raise RuntimeError("modelo roto")

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fail_prepare_session)

    payload = _chat(state, {"message": "hola", "model": "missing:1b"})

    assert payload["ok"] is False
    data = load_session(payload["session_id"])
    assert data is not None
    assert data["messages"][-1]["content"] == "hola"


def test_chat_rejects_missing_selected_model(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    state = UIState(runtime=Ci2LabConfig(model="llama3.1:8b"))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )

    payload = _chat(state, {"message": "hola", "model": ""})

    assert payload["ok"] is False
    assert "Select an installed model" in payload["error"]
    assert "llama3.1:8b" not in payload["error"]


def test_upload_file_saves_supported_file_inside_workspace(tmp_path):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    content = base64.b64encode(b"contenido local").decode("ascii")

    payload = _upload_file(
        state,
        {"name": "../Mi Documento.PDF", "content_base64": content},
    )

    assert payload["ok"] is True
    assert payload["file"]["path"] == "ci2lab_uploads/mi documento.pdf"
    assert (tmp_path / payload["file"]["path"]).read_bytes() == b"contenido local"


def test_upload_file_accepts_office_document_formats(tmp_path):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    content = base64.b64encode(b"fake docx bytes").decode("ascii")

    payload = _upload_file(state, {"name": "Tema 1.DOCX", "content_base64": content})

    assert payload["ok"] is True
    assert payload["file"]["path"] == "ci2lab_uploads/tema 1.docx"


def test_upload_file_rejects_unsupported_suffix(tmp_path):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    content = base64.b64encode(b"contenido").decode("ascii")

    payload = _upload_file(state, {"name": "documento.exe", "content_base64": content})

    assert payload["ok"] is False
    assert "Unsupported format" in payload["error"]


def test_upload_file_rejects_sensitive_names(tmp_path):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    content = base64.b64encode(b"contenido").decode("ascii")

    payload = _upload_file(state, {"name": "token.pdf", "content_base64": content})

    assert payload["ok"] is False
    assert "secrets" in payload["error"] or "tokens" in payload["error"]


def test_prompt_with_uploaded_files_reads_attachment_content(tmp_path):
    upload_dir = tmp_path / "ci2lab_uploads"
    upload_dir.mkdir()
    (upload_dir / "doc.txt").write_text("contenido importante", encoding="utf-8")

    prompt = _prompt_with_uploaded_files(
        "resume el documento",
        str(tmp_path),
        [{"name": "doc.txt", "path": "ci2lab_uploads/doc.txt"}],
    )

    assert "contenido importante" in prompt
    assert "Answer using the following content" in prompt
    assert "read_document" in prompt


def test_prompt_with_uploaded_files_reports_read_errors(tmp_path, monkeypatch):
    upload_dir = tmp_path / "ci2lab_uploads"
    upload_dir.mkdir()
    (upload_dir / "doc.pdf").write_bytes(b"%PDF simulated")
    monkeypatch.setattr(
        "ci2lab.ui.server.read_document",
        lambda *_args, **_kwargs: "Error: no se puede leer PDF porque falta pypdf",
    )

    prompt = _prompt_with_uploaded_files(
        "resume el documento",
        str(tmp_path),
        [{"name": "doc.pdf", "path": "ci2lab_uploads/doc.pdf"}],
    )

    assert "Could not read the attached file" in prompt
    assert "Contenido leído" not in prompt
    assert "Contenido leido" not in prompt


def test_prompt_with_uploaded_files_rejects_non_upload_paths(tmp_path):
    (tmp_path / "doc.txt").write_text("contenido privado", encoding="utf-8")

    prompt = _prompt_with_uploaded_files(
        "resume el documento",
        str(tmp_path),
        [{"name": "doc.txt", "path": "doc.txt"}],
    )

    assert "rejected" in prompt
    assert "contenido privado" not in prompt


def test_chat_passes_uploaded_file_content_to_agent(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path / "sessions")
    upload_dir = tmp_path / "ci2lab_uploads"
    upload_dir.mkdir()
    (upload_dir / "doc.txt").write_text("contenido del pdf simulado", encoding="utf-8")
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )
    captured: dict[str, str] = {}

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="qwen2.5-coder-1.5b",
            ollama_tag="qwen2.5-coder:1.5b",
            display_name="Qwen2.5 Coder 1.5B",
        )

    def fake_run_agent(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return "resumen"

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)
    monkeypatch.setattr("ci2lab.ui.server.run_agent", fake_run_agent)

    payload = _chat(
        state,
        {
            "message": "usa este adjunto para contestar con detalle tecnico",
            "model": "qwen2.5-coder:1.5b",
            "attachments": [{"name": "doc.txt", "path": "ci2lab_uploads/doc.txt"}],
        },
    )

    assert payload["ok"] is True
    assert captured["prompt"].startswith("usa este adjunto")
    assert "contenido del pdf simulado" in captured["prompt"]


def test_chat_returns_token_usage_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path / "sessions")
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="qwen2.5-coder-1.5b",
            ollama_tag="qwen2.5-coder:1.5b",
            display_name="Qwen2.5 Coder 1.5B",
        )

    def fake_run_agent(_prompt, _selection, *, config, **_kwargs):
        assert config.auto_confirm is True
        config.token_usage.record_call(
            TokenUsage(
                prompt_tokens=12,
                completion_tokens=4,
                total_tokens=16,
                model="qwen2.5-coder:1.5b",
            )
        )
        return "respuesta"

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)
    monkeypatch.setattr("ci2lab.ui.server.run_agent", fake_run_agent)

    payload = _chat(
        state,
        {"message": "hola", "model": "qwen2.5-coder:1.5b"},
    )

    assert payload["ok"] is True
    assert payload["usage"]["last_turn"]["total_tokens"] == 16
    assert payload["usage"]["session_total"]["prompt_tokens"] == 12


def test_chat_keeps_tools_available_from_ui(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path / "sessions")
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="qwen2.5-coder-1.5b",
            ollama_tag="qwen2.5-coder:1.5b",
            display_name="Qwen2.5 Coder 1.5B",
        )

    def fake_run_agent(_prompt, _selection, *, config, **_kwargs):
        assert config.auto_confirm is True
        assert config.write_tools_enabled is True
        return "respuesta"

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)
    monkeypatch.setattr("ci2lab.ui.server.run_agent", fake_run_agent)

    payload = _chat(
        state,
        {
            "message": "hola",
            "model": "qwen2.5-coder:1.5b",
        },
    )

    assert payload["ok"] is True


def test_chat_agents_mode_uses_multi_agent_orchestrator(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path / "sessions")
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))
    monkeypatch.setattr(
        state,
        "list_installed_models",
        lambda: ([{"name": "qwen2.5-coder:1.5b"}], None),
    )

    def fake_prepare_session(*args, **kwargs):
        return None, ModelSelection(
            model_id="qwen2.5-coder-1.5b",
            ollama_tag="qwen2.5-coder:1.5b",
            display_name="Qwen2.5 Coder 1.5B",
        )

    def fake_run_multi_agent(_prompt, _selection, *, config):
        assert config.auto_confirm is True
        return "respuesta multiagente"

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fake_prepare_session)
    monkeypatch.setattr("ci2lab.ui.server.run_multi_agent", fake_run_multi_agent)

    payload = _chat(
        state,
        {
            "message": "hola",
            "model": "qwen2.5-coder:1.5b",
            "multi_agent": True,
        },
    )

    assert payload["ok"] is True
    assert payload["answer"] == "respuesta multiagente"
    assert payload["multi_agent"] is True


def test_session_payload_returns_visible_messages(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    save_session(
        "abc123",
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "respuesta"},
        ],
        model_tag="qwen2.5-coder:1.5b",
        cwd="/tmp",
    )

    payload, status = _session_payload("abc123")

    assert status == 200
    assert payload["ok"] is True
    assert payload["session"]["model"] == "qwen2.5-coder:1.5b"
    assert payload["session"]["internal_tag"] == "abc123"
    assert payload["session"]["title"] == "Hola"
    assert [item["role"] for item in payload["session"]["messages"]] == [
        "system",
        "user",
        "assistant",
    ]


def test_delete_session_payload_removes_saved_session_file(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    save_session(
        "abc123",
        messages=[{"role": "user", "content": "hola"}],
        model_tag="qwen2.5-coder:1.5b",
        cwd="/tmp",
    )

    payload, status = _delete_session_payload("abc123")

    assert status == 200
    assert payload["ok"] is True
    assert load_session("abc123") is None

    payload, status = _delete_session_payload("abc123")

    assert status == 404
    assert payload["ok"] is False


def test_sessions_payload_includes_short_title_and_internal_tag(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    save_session(
        "abc123",
        messages=[{"role": "user", "content": "puedes resumir este documento pdf importante"}],
        model_tag="qwen2.5-coder:1.5b",
        cwd="/tmp",
    )

    sessions = _sessions_payload()

    assert sessions[0]["internal_tag"] == "abc123"
    assert sessions[0]["title"] == "Resumir documento pdf importante"


def test_system_payload_includes_hardware_disk_and_recommendations(monkeypatch):
    state = UIState(runtime=Ci2LabConfig())
    profile = build_cpu_profile_for_testing(ram_total_gb=16.0, ram_available_gb=8.0)
    monkeypatch.setattr("ci2lab.ui.server.scan_hardware", lambda: profile)
    monkeypatch.setattr("ci2lab.ui.server.score_recommendations", lambda *args, **kwargs: [])

    payload = _system_payload(state)

    assert payload["ok"] is True
    assert payload["hardware"]["ram_total_gb"] == 16.0
    assert payload["disk"]["free_gb"] >= 0
    assert payload["recommendations"] == []


def test_tools_payload_exposes_new_agent_tools(tmp_path):
    state = UIState(runtime=Ci2LabConfig(workspace=str(tmp_path)))

    payload = _tools_payload(state)

    names = {tool["name"] for tool in payload["tools"]}
    assert payload["ok"] is True
    assert {"read_document", "todo_write", "web_fetch", "git_status", "mcp_call"} <= names
    assert any(action["tool"] == "read_document" for action in payload["actions"])
    assert ".docx" in payload["supported_uploads"]


def test_pull_task_progress_is_computed_from_ollama_events():
    state = UIState(runtime=Ci2LabConfig())
    state.pull_tasks["task1"] = {
        "id": "task1",
        "tag": "model:1b",
        "status": "Preparando descarga",
        "completed": 0,
        "total": 0,
        "percent": 0.0,
        "done": False,
        "ok": None,
        "error": None,
        "layers": {},
    }

    _record_pull_event(
        state,
        "task1",
        {"status": "pulling layer", "digest": "sha256:a", "total": 100, "completed": 25},
    )
    payload, status = _pull_task_payload(state, "task1")

    assert status == 200
    assert payload["task"]["percent"] == 25.0
    assert payload["task"]["completed"] == 25
    assert payload["task"]["total"] == 100

    _record_pull_event(state, "task1", {"status": "success"})
    payload, _ = _pull_task_payload(state, "task1")

    assert payload["task"]["done"] is True
    assert payload["task"]["ok"] is True
    assert payload["task"]["percent"] == 100.0


def test_delete_task_payload_reports_progress_and_completion():
    state = UIState(runtime=Ci2LabConfig())
    state.delete_tasks["delete1"] = {
        "id": "delete1",
        "tag": "model:1b",
        "status": "Eliminando modelo local",
        "percent": 65.0,
        "done": False,
        "ok": None,
        "error": None,
    }

    payload, status = _delete_task_payload(state, "delete1")

    assert status == 200
    assert payload["task"]["percent"] == 65.0
    assert payload["task"]["done"] is False

    _finish_delete_task(state, "delete1", ok=True, status="Modelo desinstalado")
    payload, _ = _delete_task_payload(state, "delete1")

    assert payload["task"]["done"] is True
    assert payload["task"]["ok"] is True
    assert payload["task"]["percent"] == 100.0
