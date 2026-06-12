"""Minimal MCP client over stdio (JSON-RPC 2.0 with Content-Length framing)."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

_INIT_PARAMS = {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "ci2lab", "version": "0.1.0"},
}


@dataclass
class McpTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class McpClient:
    server_name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    _proc: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _next_id: int = 1
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    tools: list[McpTool] = field(default_factory=list)

    def connect(self, timeout: float = 30.0) -> None:
        if self._proc is not None:
            return
        merged_env = {**os.environ, **self.env}
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            cwd=self.cwd,
        )
        self._request("initialize", _INIT_PARAMS, timeout=timeout)
        self._notify("notifications/initialized", {})
        listed = self._request("tools/list", {}, timeout=timeout)
        self.tools = self._parse_tools(listed or {})

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None

    def call_tool(self, tool_name: str, arguments: dict[str, Any], *, timeout: float = 60.0) -> str:
        if self._proc is None:
            return "Error: MCP server not connected"
        result = self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=timeout,
        )
        return self._format_tool_result(result)

    def _parse_tools(self, payload: dict[str, Any]) -> list[McpTool]:
        tools: list[McpTool] = []
        for item in payload.get("tools") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            tools.append(
                McpTool(
                    server=self.server_name,
                    name=str(name),
                    description=str(item.get("description") or ""),
                    input_schema=item.get("inputSchema") or {"type": "object", "properties": {}},
                )
            )
        return tools

    @staticmethod
    def _format_tool_result(result: dict[str, Any] | None) -> str:
        if not result:
            return "(empty MCP result)"
        if result.get("isError"):
            return f"Error: {result}"
        content = result.get("content") or []
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(parts).strip() or json.dumps(result, ensure_ascii=False)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            while True:
                msg = self._read_message(timeout=timeout)
                if msg is None:
                    raise TimeoutError(f"MCP {self.server_name}: timeout waiting for {method}")
                if msg.get("id") == req_id:
                    if "error" in msg:
                        err = msg["error"]
                        raise RuntimeError(
                            f"MCP {self.server_name} {method}: {err.get('message', err)}"
                        )
                    result = msg.get("result")
                    return result if isinstance(result, dict) else {}

    def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP process not running")
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _read_message(self, *, timeout: float) -> dict[str, Any] | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._proc.stdout.read(1)
            if not chunk:
                return None
            buf += chunk

        header_text = buf.decode("ascii", errors="replace")
        length_line = header_text.split("\r\n", 1)[0]
        if not length_line.lower().startswith("content-length:"):
            return None
        length = int(length_line.split(":", 1)[1].strip())
        body = self._read_exact(self._proc.stdout, length, timeout)
        if body is None:
            return None
        return json.loads(body.decode("utf-8"))

    def _read_exact(self, stream, n: int, timeout: float) -> bytes | None:
        data = b""
        while len(data) < n:
            chunk = stream.read(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data
