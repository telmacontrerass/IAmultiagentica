import json

from ci2lab.harness.session import (
    delete_session,
    is_delete_session_request,
    load_session,
    new_session_id,
    save_session,
)


def test_session_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    sid = new_session_id()
    messages = [{"role": "user", "content": "hello"}]
    path = save_session(sid, messages=messages, model_tag="m:1", cwd="/tmp")
    assert path.is_file()
    data = load_session(sid)
    assert data is not None
    assert data["messages"][0]["content"] == "hello"


def test_load_session_normalizes_null_content(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    sid = "legacy_null"
    (tmp_path / f"{sid}.json").write_text(
        json.dumps({
            "id": sid,
            "model_tag": "m:1",
            "cwd": "/tmp",
            "messages": [{"role": "assistant", "content": None}],
        }),
        encoding="utf-8",
    )

    data = load_session(sid)

    assert data is not None
    assert data["messages"][0]["content"] == ""


def test_delete_session_removes_saved_file(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    sid = new_session_id()
    path = save_session(
        sid,
        messages=[{"role": "user", "content": "hello"}],
        model_tag="m:1",
        cwd="/tmp",
    )

    assert path.is_file()
    assert delete_session(sid)
    assert not path.exists()
    assert not delete_session(sid)


def test_is_delete_session_request_accepts_natural_language():
    assert is_delete_session_request("delete what you just saved")
    assert is_delete_session_request("remove the saved session")
    assert is_delete_session_request("/delete")
    assert not is_delete_session_request("delete the file test.pdf")
