"""ASCII output tests for `ci2lab doctor` (Windows/cp1252 compatible)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from ci2lab.cli.commands.doctor import (
    _DOCTOR_ERROR,
    _DOCTOR_OK,
    _DOCTOR_WARN,
    _cmd_doctor,
    _missing_document_dependencies,
)
from ci2lab.config import Ci2LabConfig


def test_doctor_markers_are_ascii():
    assert _DOCTOR_OK.isascii()
    assert _DOCTOR_ERROR.isascii()
    assert _DOCTOR_WARN.isascii()
    assert "\u2713" not in _DOCTOR_OK
    assert "\u2717" not in _DOCTOR_ERROR


def test_cmd_doctor_output_encodes_cp1252(monkeypatch):
    buf = StringIO()
    monkeypatch.setattr("ci2lab.cli.commands.doctor.console", Console(file=buf, width=120))
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"models": [{"name": "llama3.1:8b"}]}

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse())

    runtime = Ci2LabConfig()
    code = _cmd_doctor(runtime)

    output = buf.getvalue()
    output.encode("cp1252")
    assert code == 0
    assert _DOCTOR_OK in output
    assert "\u2713" not in output
    assert "\u2717" not in output


def test_cmd_doctor_ollama_error_encodes_cp1252(monkeypatch):
    buf = StringIO()
    monkeypatch.setattr("ci2lab.cli.commands.doctor.console", Console(file=buf, width=120))
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    def fail_get(*args, **kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("httpx.get", fail_get)

    runtime = Ci2LabConfig()
    code = _cmd_doctor(runtime)

    output = buf.getvalue()
    output.encode("cp1252")
    assert code == 0
    assert _DOCTOR_WARN in output
    assert "\u2717" not in output


def test_cmd_doctor_backend_keyboard_interrupt_is_clean(monkeypatch):
    buf = StringIO()
    monkeypatch.setattr("ci2lab.cli.commands.doctor.console", Console(file=buf, width=120))
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("httpx.get", interrupt)

    runtime = Ci2LabConfig()
    code = _cmd_doctor(runtime)

    output = buf.getvalue()
    output.encode("cp1252")
    assert code == 130
    assert "Interrupted" in output


def test_cmd_doctor_openai_models_endpoint(monkeypatch):
    buf = StringIO()
    monkeypatch.setattr("ci2lab.cli.commands.doctor.console", Console(file=buf, width=120))
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"id": "local-openai-model"}]}

    calls = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"].connect == 1.0
        return FakeResponse()

    monkeypatch.setattr("httpx.get", fake_get)

    runtime = Ci2LabConfig(
        backend="openai",
        backend_url="http://localhost:8000/v1",
        model="local-openai-model",
    )
    code = _cmd_doctor(runtime)

    output = buf.getvalue()
    output.encode("cp1252")
    assert code == 0
    assert "OpenAI-compatible backend" in output
    assert calls == ["http://localhost:8000/v1/models"]


def test_cmd_doctor_openai_falls_back_to_chat(monkeypatch):
    buf = StringIO()
    monkeypatch.setattr("ci2lab.cli.commands.doctor.console", Console(file=buf, width=120))
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: object())

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    def fail_get(*args, **kwargs):
        raise ConnectionError("no /models")

    posted = {}

    def fake_post(url, json, *args, **kwargs):
        posted["url"] = url
        posted["json"] = json
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"].connect == 1.0
        return FakeResponse()

    monkeypatch.setattr("httpx.get", fail_get)
    monkeypatch.setattr("httpx.post", fake_post)

    runtime = Ci2LabConfig(
        backend="openai",
        backend_url="http://localhost:8000/v1",
        model="local-openai-model",
    )
    code = _cmd_doctor(runtime)

    output = buf.getvalue()
    output.encode("cp1252")
    assert code == 0
    assert "chat/completions responded" in output
    assert posted["url"] == "http://localhost:8000/v1/chat/completions"
    assert posted["json"]["model"] == "local-openai-model"


def test_missing_document_dependencies_reports_missing_modules(monkeypatch):
    def fake_find_spec(name):
        return None if name == "docx" else object()

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)

    assert _missing_document_dependencies() == [("docx", "Word/DOCX")]
