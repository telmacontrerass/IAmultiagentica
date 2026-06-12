from ci2lab.config import Ci2LabConfig
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMModelNotFoundError
from ci2lab.harness.session import load_session, save_session
from ci2lab.hardware.profile import build_cpu_profile_for_testing
from ci2lab.ui.server import (
    UIState,
    _chat,
    _content_type,
    _delete_task_payload,
    _finish_delete_task,
    _health_payload,
    _pull_task_payload,
    _record_pull_event,
    _session_payload,
    _sessions_payload,
    _system_payload,
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


def test_chat_returns_llm_error_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    state = UIState(runtime=Ci2LabConfig())

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

    def fail_prepare_session(*args, **kwargs):
        raise RuntimeError("modelo roto")

    monkeypatch.setattr("ci2lab.ui.server.prepare_session", fail_prepare_session)

    payload = _chat(state, {"message": "hola", "model": "missing:1b"})

    assert payload["ok"] is False
    data = load_session(payload["session_id"])
    assert data is not None
    assert data["messages"][-1]["content"] == "hola"


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
