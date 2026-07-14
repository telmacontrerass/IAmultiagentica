"""Safe Windows-compatible lifecycle for an externally installed llama-server."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO

from ci2lab.runtime.base import RuntimeEndpoint, RuntimeHealth


def choose_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def resolve_llama_server(explicit: str | Path | None = None, configured: str | None = None) -> Path:
    candidate = str(explicit or os.environ.get("CI2LAB_LLAMA_SERVER") or configured or "")
    found = candidate or shutil.which("llama-server") or shutil.which("llama-server.exe")
    if not found or not Path(found).is_file():
        raise FileNotFoundError(
            "llama-server not found; use --llama-server-path or CI2LAB_LLAMA_SERVER"
        )
    return Path(found).resolve()


class LlamaCppRuntime:
    def __init__(
        self,
        model_path: Path,
        *,
        binary: Path | str | None = None,
        context_length: int = 16000,
        startup_timeout: float = 120,
        log_dir: Path,
        template_path: Path | None = None,
    ) -> None:
        self.model_path = model_path.resolve()
        self.binary = resolve_llama_server(binary)
        self.context_length = context_length
        self.startup_timeout = startup_timeout
        self.log_dir = log_dir.resolve()
        self.template_path = template_path.resolve() if template_path else None
        self.port = choose_free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.was_started = False
        self._stdout: IO[bytes] | None = None
        self._stderr: IO[bytes] | None = None
        self.endpoint: RuntimeEndpoint | None = None

    def build_command(self) -> list[str]:
        command = [
            str(self.binary),
            "--model",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.context_length),
        ]
        if self.template_path is not None:
            command.extend(["--jinja", "--chat-template-file", str(self.template_path)])
        return command

    def start(self) -> RuntimeEndpoint:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._stdout = (self.log_dir / "runtime_stdout.log").open("wb")
        self._stderr = (self.log_dir / "runtime_stderr.log").open("wb")
        command = self.build_command()
        (self.log_dir / "runtime_command.json").write_text(
            json.dumps({"argv": command}, indent=2) + "\n", encoding="utf-8"
        )
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout,
                stderr=self._stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.was_started = True
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        f"llama-server exited during startup ({self.process.returncode})"
                    )
                health = self.health_check()
                if health.healthy:
                    model_id = self._model_id()
                    self.endpoint = RuntimeEndpoint(
                        f"http://127.0.0.1:{self.port}/v1", model_id, self.port
                    )
                    return self.endpoint
                time.sleep(0.2)
            raise TimeoutError(
                f"llama-server did not become healthy within {self.startup_timeout:g}s"
            )
        except BaseException:
            self.stop()
            raise

    def _request(self, path: str) -> tuple[int, object]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=2) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}

    def _model_id(self) -> str:
        _status, payload = self._request("/v1/models")
        models = payload.get("data", []) if isinstance(payload, dict) else []
        if not models:
            raise RuntimeError("llama-server /v1/models returned no model")
        return str(models[0].get("id") or self.model_path.name)

    def health_check(self) -> RuntimeHealth:
        try:
            health_status, _ = self._request("/health")
            models_status, payload = self._request("/v1/models")
            visible = isinstance(payload, dict) and bool(payload.get("data"))
            return RuntimeHealth(
                health_status == 200 and models_status == 200 and visible,
                health_status,
                models_status,
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return RuntimeHealth(False, error=str(exc))

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.process = None
        for stream in (self._stdout, self._stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def __enter__(self) -> LlamaCppRuntime:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()
