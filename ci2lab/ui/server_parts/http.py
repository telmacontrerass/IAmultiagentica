"""HTTP server wiring for the local Ci2Lab UI."""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import unquote, urlparse

from ci2lab.config import Ci2LabConfig
from ci2lab.runtime.ollama import fetch_installed_models, ollama_base_url

STATIC_PACKAGE = "ci2lab.ui.static"


class UIState:
    def __init__(self, *, runtime: Ci2LabConfig) -> None:
        self.runtime = runtime
        self.pull_lock = threading.Lock()
        self.pull_tasks: dict[str, dict[str, Any]] = {}
        self.delete_lock = threading.Lock()
        self.delete_tasks: dict[str, dict[str, Any]] = {}
        self.chat_lock = threading.Lock()
        self.chat_cancellations: dict[str, threading.Event] = {}

    @property
    def ollama_base_url(self) -> str:
        return ollama_base_url(self.runtime.backend_url)

    def list_installed_models(self) -> tuple[list[dict[str, Any]], str | None]:
        return fetch_installed_models(self.runtime.backend_url)

    def begin_chat_request(self, request_id: str) -> threading.Event | None:
        request_id = request_id.strip()
        if not request_id:
            return None
        with self.chat_lock:
            event = threading.Event()
            self.chat_cancellations[request_id] = event
            return event

    def cancel_chat_request(self, request_id: str) -> bool:
        request_id = request_id.strip()
        if not request_id:
            return False
        with self.chat_lock:
            event = self.chat_cancellations.get(request_id)
            if not event:
                return False
            event.set()
            return True

    def finish_chat_request(self, request_id: str) -> None:
        request_id = request_id.strip()
        if not request_id:
            return
        with self.chat_lock:
            self.chat_cancellations.pop(request_id, None)


def run_ui(
    runtime: Ci2LabConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> int:
    """Start the local web UI and block until interrupted."""
    state = UIState(runtime=runtime)
    server = ThreadingHTTPServer((host, port), handler_factory(state))
    url = f"http://{host}:{server.server_port}"
    print(f"Ci2Lab UI local: {url}")
    print("Press Ctrl+C to stop the server.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nUI server stopped.")
        return 130
    finally:
        server.server_close()
    return 0


def handler_factory(state: UIState):
    class UIRequestHandler(BaseHTTPRequestHandler):
        server_version = "Ci2LabUI/0.1"

        def do_GET(self) -> None:  # noqa: N802
            facade = _facade()
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_static("index.html")
                return
            if parsed.path.startswith("/static/"):
                self._serve_static(parsed.path.removeprefix("/static/"))
                return
            if parsed.path == "/api/health":
                self._json(facade._health_payload(state))
                return
            if parsed.path == "/api/models":
                self._json(facade._models_payload(state))
                return
            if parsed.path == "/api/system":
                self._json(facade._system_payload(state))
                return
            if parsed.path == "/api/tools":
                self._json(facade._tools_payload(state))
                return
            if parsed.path == "/api/projects":
                self._json({"ok": True, "projects": facade._list_projects()})
                return
            if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/sources"):
                project_id = unquote(parsed.path.split("/")[-2]).strip()
                payload = facade._list_project_sources(project_id)
                self._json(payload, status=200 if payload.get("ok") else 404)
                return
            if parsed.path.startswith("/api/projects/"):
                project_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                project = facade._get_project(project_id)
                self._json(
                    {"ok": bool(project), "project": project, "error": None if project else "Project not found."},
                    status=200 if project else 404,
                )
                return
            if parsed.path.startswith("/api/models/pull/"):
                task_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = facade._pull_task_payload(state, task_id)
                self._json(payload, status=status)
                return
            if parsed.path.startswith("/api/models/delete/"):
                task_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = facade._delete_task_payload(state, task_id)
                self._json(payload, status=status)
                return
            if parsed.path == "/api/sessions":
                self._json({"sessions": facade._sessions_payload()})
                return
            if parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = facade._session_payload(session_id)
                self._json(payload, status=status)
                return
            if parsed.path == "/api/runs":
                self._json({"runs": facade._list_runs(state.runtime.runs_dir)})
                return
            self._json({"error": "Not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            facade = _facade()
            parsed = urlparse(self.path)
            payload = self._read_json()
            if parsed.path == "/api/chat/start":
                self._json(facade._chat_start(state, payload))
                return
            if parsed.path == "/api/chat/cancel":
                self._json(facade._chat_cancel(state, payload))
                return
            if parsed.path == "/api/chat":
                self._json(facade._chat(state, payload))
                return
            if parsed.path == "/api/models/pull":
                self._json(facade._pull_model(state, payload))
                return
            if parsed.path == "/api/models/delete":
                self._json(facade._delete_model(state, payload))
                return
            if parsed.path == "/api/files/upload":
                self._json(facade._upload_file(state, payload))
                return
            if parsed.path == "/api/projects":
                result = facade._create_project(str(payload.get("name") or ""))
                self._json(result, status=201 if result.get("ok") else 400)
                return
            if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/sources"):
                project_id = unquote(parsed.path.split("/")[-2]).strip()
                result = facade._add_project_source(project_id, payload)
                self._json(result, status=201 if result.get("ok") else 400)
                return
            self._json({"error": "Not found"}, status=404)

        def do_PATCH(self) -> None:  # noqa: N802
            facade = _facade()
            parsed = urlparse(self.path)
            payload = self._read_json()
            if parsed.path.startswith("/api/projects/"):
                project_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                result = facade._rename_project(project_id, str(payload.get("name") or ""))
                self._json(result, status=200 if result.get("ok") else 400)
                return
            self._json({"error": "Not found"}, status=404)

        def do_DELETE(self) -> None:  # noqa: N802
            facade = _facade()
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = facade._delete_session_payload(session_id)
                self._json(payload, status=status)
                return
            if parsed.path.startswith("/api/projects/") and "/sources/" in parsed.path:
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 5:
                    project_id = unquote(parts[2]).strip()
                    source_id = unquote(parts[4]).strip()
                    result = facade._delete_project_source(project_id, source_id)
                    self._json(result, status=200 if result.get("ok") else 404)
                    return
            if parsed.path.startswith("/api/projects/"):
                project_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                result = facade._delete_project(project_id)
                self._json(result, status=200 if result.get("ok") else 404)
                return
            self._json({"error": "Not found"}, status=404)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return loaded if isinstance(loaded, dict) else {}

        def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

        def _serve_static(self, name: str) -> None:
            clean = name.strip("/").replace("\\", "/")
            if not clean:
                clean = "index.html"
            if ".." in clean.split("/"):
                self._json({"error": "Invalid path"}, status=400)
                return
            try:
                ref = resources.files(STATIC_PACKAGE).joinpath(clean)
                body = ref.read_bytes()
            except FileNotFoundError:
                self._json({"error": "Not found"}, status=404)
                return
            content_type = content_type_for(clean)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return UIRequestHandler


def content_type_for(name: str) -> str:
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".css"):
        return "text/css; charset=utf-8"
    if name.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if name.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def _facade():
    from ci2lab.ui import server as facade

    return facade
