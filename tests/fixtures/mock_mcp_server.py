"""Minimal MCP stdio server for tests."""

from __future__ import annotations

import json
import sys


def _read_message() -> dict:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            raise EOFError
        buf += chunk
    length = int(buf.decode().split("\r\n", 1)[0].split(":", 1)[1].strip())
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _send(payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


def main() -> None:
    while True:
        try:
            msg = _read_message()
        except EOFError:
            break
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "mock", "version": "0.1"},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            })
        elif method == "tools/call":
            params = msg.get("params") or {}
            text = (params.get("arguments") or {}).get("text", "")
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"echo:{text}"}],
                },
            })
        elif req_id is not None:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"unknown method {method}"},
            })


if __name__ == "__main__":
    main()
