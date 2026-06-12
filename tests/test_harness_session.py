import json

from ci2lab.harness.session import load_session, new_session_id, save_session


def test_session_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("ci2lab.harness.session.sessions_dir", lambda: tmp_path)
    sid = new_session_id()
    messages = [{"role": "user", "content": "hola"}]
    path = save_session(sid, messages=messages, model_tag="m:1", cwd="/tmp")
    assert path.is_file()
    data = load_session(sid)
    assert data is not None
    assert data["messages"][0]["content"] == "hola"


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
