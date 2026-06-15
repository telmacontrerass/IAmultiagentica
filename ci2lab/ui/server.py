"""Local-only HTTP server for the Ci2Lab web UI."""

from __future__ import annotations

import json
import os
import re
import base64
import binascii
import shutil
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from ci2lab.config import Ci2LabConfig
from ci2lab.harness import run_agent
from ci2lab.harness.document_answer import maybe_answer_document_request
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.session import delete_session, list_sessions, load_session, new_session_id, save_session
from ci2lab.harness.mcp.config import load_mcp_config
from ci2lab.harness.permissions import CONFIRM_TOOLS
from ci2lab.harness.skills.loader import load_skills
from ci2lab.harness.tools.filesystem import (
    SUPPORTED_DOCUMENT_SUFFIXES,
    read_document,
    read_file,
)
from ci2lab.harness.tools.registry import FUNCTION_SCHEMAS
from ci2lab.harness.tools.secret_files import is_sensitive_path
from ci2lab.hardware import scan_hardware
from ci2lab.pipeline import build_agent_config, prepare_session
from ci2lab.router.catalog import load_model_catalog
from ci2lab.runtime.ollama import fetch_installed_models, is_catalog_model_installed, ollama_base_url
from ci2lab.router.recommend import (
    build_display_recommendations,
    recommendation_pool_size,
    score_recommendations,
)

STATIC_PACKAGE = "ci2lab.ui.static"
UPLOAD_DIR_NAME = "ci2lab_uploads"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_UPLOAD_SUFFIXES = {
    ".csv",
    ".css",
    ".docx",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".pptx",
    ".py",
    ".rst",
    ".rtf",
    ".text",
    ".toml",
    ".ts",
    ".tsv",
    ".txt",
    ".xml",
    ".xlsx",
    ".yaml",
    ".yml",
}

DOCUMENT_UPLOAD_SUFFIXES = SUPPORTED_DOCUMENT_SUFFIXES | {".rtf"}

UI_ACTIONS: list[dict[str, str]] = [
    {
        "id": "read_document",
        "label": "Resumir adjunto",
        "tool": "read_document",
        "group": "Documentos",
        "prompt": "Lee y resume los archivos adjuntos. Extrae ideas principales y puntos accionables.",
    },
    {
        "id": "workspace_tree",
        "label": "Mapa del proyecto",
        "tool": "tree",
        "group": "Explorar",
        "prompt": "Haz un mapa breve del proyecto usando tree, file_info y read_file solo cuando haga falta.",
    },
    {
        "id": "search_workspace",
        "label": "Buscar en archivos",
        "tool": "grep",
        "group": "Explorar",
        "prompt": "Busca en el workspace el texto o concepto que te indique y dime en qué archivos aparece.",
    },
    {
        "id": "git_status",
        "label": "Estado Git",
        "tool": "git_status",
        "group": "Git",
        "prompt": "Muestra el estado git del workspace y resume los cambios pendientes.",
    },
    {
        "id": "git_diff",
        "label": "Revisar diff",
        "tool": "git_diff",
        "group": "Git",
        "prompt": "Revisa el git diff actual. Señala riesgos, conflictos lógicos y pruebas recomendadas.",
    },
    {
        "id": "todo_plan",
        "label": "Plan de tareas",
        "tool": "todo_write",
        "group": "Planificación",
        "prompt": "Crea o actualiza una lista de tareas para este trabajo usando todo_write.",
    },
    {
        "id": "web_reference",
        "label": "Consultar URL",
        "tool": "web_fetch",
        "group": "Web",
        "prompt": "Consulta esta URL con web_fetch y resume lo importante: https://",
    },
    {
        "id": "notebook_edit",
        "label": "Editar notebook",
        "tool": "notebook_edit",
        "group": "Notebook",
        "prompt": "Edita el notebook indicado con notebook_edit. Ruta, celda y contenido:",
    },
    {
        "id": "skill",
        "label": "Usar skill",
        "tool": "skill",
        "group": "Skills",
        "prompt": "Si hay una skill adecuada, invócala con la herramienta skill y sigue sus instrucciones.",
    },
    {
        "id": "mcp_call",
        "label": "Usar MCP",
        "tool": "mcp_call",
        "group": "MCP",
        "prompt": "Usa una herramienta MCP configurada si encaja. Servidor, herramienta y argumentos:",
    },
]


def run_ui(
    runtime: Ci2LabConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> int:
    """Start the local web UI and block until interrupted."""
    state = UIState(runtime=runtime)
    server = ThreadingHTTPServer((host, port), _handler_factory(state))
    url = f"http://{host}:{server.server_port}"
    print(f"Ci2Lab UI local: {url}")
    print("Pulsa Ctrl+C para parar el servidor.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor UI detenido.")
        return 130
    finally:
        server.server_close()
    return 0


class UIState:
    def __init__(self, *, runtime: Ci2LabConfig) -> None:
        self.runtime = runtime
        self.pull_lock = threading.Lock()
        self.pull_tasks: dict[str, dict[str, Any]] = {}
        self.delete_lock = threading.Lock()
        self.delete_tasks: dict[str, dict[str, Any]] = {}

    @property
    def ollama_base_url(self) -> str:
        return ollama_base_url(self.runtime.backend_url)

    def list_installed_models(self) -> tuple[list[dict[str, Any]], str | None]:
        return fetch_installed_models(self.runtime.backend_url)


def _handler_factory(state: UIState):
    class UIRequestHandler(BaseHTTPRequestHandler):
        server_version = "Ci2LabUI/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_static("index.html")
                return
            if parsed.path.startswith("/static/"):
                self._serve_static(parsed.path.removeprefix("/static/"))
                return
            if parsed.path == "/api/health":
                self._json(_health_payload(state))
                return
            if parsed.path == "/api/models":
                self._json(_models_payload(state))
                return
            if parsed.path == "/api/system":
                self._json(_system_payload(state))
                return
            if parsed.path == "/api/tools":
                self._json(_tools_payload(state))
                return
            if parsed.path.startswith("/api/models/pull/"):
                task_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = _pull_task_payload(state, task_id)
                self._json(payload, status=status)
                return
            if parsed.path.startswith("/api/models/delete/"):
                task_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = _delete_task_payload(state, task_id)
                self._json(payload, status=status)
                return
            if parsed.path == "/api/sessions":
                self._json({"sessions": _sessions_payload()})
                return
            if parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = _session_payload(session_id)
                self._json(payload, status=status)
                return
            if parsed.path == "/api/runs":
                self._json({"runs": _list_runs(state.runtime.runs_dir)})
                return
            self._json({"error": "Not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            payload = self._read_json()
            if parsed.path == "/api/chat/start":
                self._json(_chat_start(state, payload))
                return
            if parsed.path == "/api/chat":
                self._json(_chat(state, payload))
                return
            if parsed.path == "/api/models/pull":
                self._json(_pull_model(state, payload))
                return
            if parsed.path == "/api/models/delete":
                self._json(_delete_model(state, payload))
                return
            if parsed.path == "/api/files/upload":
                self._json(_upload_file(state, payload))
                return
            self._json({"error": "Not found"}, status=404)

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.rsplit("/", 1)[-1]).strip()
                payload, status = _delete_session_payload(session_id)
                self._json(payload, status=status)
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
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            content_type = _content_type(clean)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return UIRequestHandler


def _health_payload(state: UIState) -> dict[str, Any]:
    installed, error = state.list_installed_models()
    return {
        "ok": error is None,
        "ollama_error": error,
        "ollama_base_url": state.ollama_base_url,
        "installed_count": len(installed),
        "workspace": state.runtime.workspace or os.getcwd(),
        "model": state.runtime.model,
        "runs_dir": state.runtime.runs_dir,
        "local_only": True,
    }


def _models_payload(state: UIState) -> dict[str, Any]:
    installed, error = state.list_installed_models()
    installed_names = {item["name"] for item in installed}
    profile = None
    try:
        profile, _ = prepare_session(
            "",
            force_model=state.runtime.model,
            tool_mode_override=None,
            backend_url=state.runtime.backend_url,
            pull=False,
        )
    except Exception:  # noqa: BLE001
        profile = None

    recommendations = {}
    if profile is not None:
        try:
            recommendations = {
                item.model.id: item
                for item in score_recommendations("", profile=profile, limit=len(load_model_catalog()))
            }
        except Exception:  # noqa: BLE001
            recommendations = {}

    catalog = []
    for model in load_model_catalog():
        item = recommendations.get(model.id)
        catalog.append({
            "id": model.id,
            "display_name": model.display_name,
            "family": model.family,
            "ollama_tag": model.ollama_tag,
            "categories": model.categories,
            "tier": model.tier,
            "benchmark_score": model.benchmark_score,
            "ram_inference_gb": model.ram_inference_gb,
            "vram_min_gb": model.vram_min_gb,
            "installed": is_catalog_model_installed(model.ollama_tag, installed_names),
            "fit_label": getattr(item, "fit_label", None),
            "recommendation_status": getattr(item, "recommendation_status", None),
        })
    return {
        "catalog": catalog,
        "installed": installed,
        "ollama_error": error,
    }


def _system_payload(state: UIState) -> dict[str, Any]:
    workspace = state.runtime.workspace or os.getcwd()
    try:
        profile = scan_hardware()
        installed_names = {item["name"] for item in state.list_installed_models()[0]}
        pool_limit = recommendation_pool_size(4)
        scored = score_recommendations("", profile=profile, limit=pool_limit)
        recommendations = [
            {
                "id": entry.item.model.id,
                "display_name": entry.item.model.display_name,
                "ollama_tag": entry.item.model.ollama_tag,
                "fit_label": entry.item.fit_label,
                "status": entry.item.recommendation_status,
                "reason": entry.item.reason,
                "memory_required_gb": entry.item.memory_required_gb,
                "memory_budget_gb": entry.item.memory_budget_gb,
                "memory_usage_percent": entry.item.memory_usage_percent,
                "remaining_memory_gb": entry.item.remaining_memory_gb,
                "installed": entry.installed,
                "installation_label": entry.installation_label,
            }
            for entry in build_display_recommendations(
                scored,
                installed_names,
                limit=4,
            )
        ]
        return {
            "ok": True,
            "hardware": profile.to_dict(),
            "disk": _disk_payload(workspace),
            "recommendations": recommendations,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "hardware": None,
            "disk": _disk_payload(workspace),
            "recommendations": [],
        }


def _tools_payload(state: UIState) -> dict[str, Any]:
    workspace = str(state.runtime.workspace or os.getcwd())
    skills = load_skills(workspace)
    mcp_servers = load_mcp_config(workspace)
    tools = []
    for schema in FUNCTION_SCHEMAS:
        function = schema.get("function", {})
        name = str(function.get("name") or "")
        if not name:
            continue
        group = _tool_group(name)
        tools.append({
            "name": name,
            "group": group,
            "description": str(function.get("description") or ""),
            "requires_confirmation": name in CONFIRM_TOOLS,
            "web_status": _tool_web_status(name),
        })

    return {
        "ok": True,
        "tools": tools,
        "actions": UI_ACTIONS,
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
                "user_invocable": skill.user_invocable,
            }
            for skill in sorted(skills.values(), key=lambda item: item.name)
        ],
        "mcp_servers": [
            {
                "name": server.name,
                "command": server.command,
                "configured": True,
            }
            for server in sorted(mcp_servers, key=lambda item: item.name)
        ],
        "supported_uploads": sorted(SUPPORTED_UPLOAD_SUFFIXES),
        "document_uploads": sorted(DOCUMENT_UPLOAD_SUFFIXES),
    }


def _chat_start(state: UIState, payload: dict[str, Any]) -> dict[str, Any]:
    model = str(payload.get("model") or state.runtime.model).strip()
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    technical_mode = bool(payload.get("technical_mode"))
    warnings: list[str] = []

    try:
        _, selection = prepare_session(
            "",
            force_model=model,
            tool_mode_override=None,
            backend_url=state.runtime.backend_url,
            pull=False,
        )
        model = selection.ollama_tag
        display_name = selection.display_name
        tool_mode = selection.tool_mode
        warnings = list(selection.warnings)
    except Exception as exc:  # noqa: BLE001
        display_name = model
        tool_mode = state.runtime.tool_mode
        warnings = [str(exc)]

    return {
        "ok": True,
        "session_id": session_id,
        "model": model,
        "display_name": display_name,
        "tool_mode": tool_mode,
        "cwd": workspace,
        "ui_mode": "tecnico" if technical_mode else "protegido",
        "security_profile": state.runtime.security.profile,
        "security_engine": state.runtime.security.engine,
        "warnings": warnings,
    }


def _tool_group(name: str) -> str:
    if name in {"read_document", "read_file", "ls", "grep", "glob", "file_info", "tree", "inspect_file"}:
        return "Explorar"
    if name in {"write_file", "edit_file", "notebook_edit"}:
        return "Editar"
    if name in {"git_status", "git_diff"}:
        return "Git"
    if name in {"todo_write", "ask_user"}:
        return "Planificación"
    if name == "web_fetch":
        return "Web"
    if name == "skill":
        return "Skills"
    if name == "mcp_call" or name.startswith("mcp__"):
        return "MCP"
    if name == "bash":
        return "Sistema"
    return "Otras"


def _tool_web_status(name: str) -> str:
    if name == "ask_user":
        return "Solo terminal; en la web pregunta directamente en el chat."
    if name in CONFIRM_TOOLS:
        return "Requiere modo técnico para autoaprobar en la web."
    return "Disponible desde el chat."


def _disk_payload(workspace: str) -> dict[str, Any]:
    path = Path(workspace or os.getcwd())
    if not path.exists():
        path = Path.cwd()
    usage = shutil.disk_usage(path)
    total_gb = _bytes_to_gb(usage.total)
    free_gb = _bytes_to_gb(usage.free)
    used_gb = _bytes_to_gb(usage.used)
    used_percent = round((usage.used / usage.total * 100), 1) if usage.total else 0.0
    return {
        "path": str(path),
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "used_percent": used_percent,
        "free_percent": round(100 - used_percent, 1),
    }


def _bytes_to_gb(value: int | float) -> float:
    return round(float(value) / (1024**3), 2)


def _chat(state: UIState, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("message") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Escribe un mensaje antes de enviar."}

    model = str(payload.get("model") or state.runtime.model).strip()
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    attachments = _normalize_attachments(payload.get("attachments"))
    prompt_for_model = _prompt_with_uploaded_files(prompt, workspace, attachments)
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    technical_mode = bool(payload.get("technical_mode"))
    stream = bool(payload.get("stream", False))
    loaded = load_session(session_id)
    messages = loaded.get("messages") if loaded else None
    _save_pending_session(
        session_id=session_id,
        messages=messages,
        prompt=prompt,
        model_tag=model,
        cwd=workspace,
    )
    direct_answer = (
        maybe_answer_document_request(prompt, [prompt_for_model])
        if attachments
        else None
    )
    if direct_answer:
        _save_completed_session(
            session_id=session_id,
            messages=messages,
            prompt=prompt,
            answer=direct_answer,
            model_tag=model,
            cwd=workspace,
        )
        return {
            "ok": True,
            "answer": direct_answer,
            "session_id": session_id,
            "model": model,
            "display_name": model,
        }

    try:
        _, selection = prepare_session(
            prompt_for_model,
            force_model=model,
            tool_mode_override=None,
            backend_url=state.runtime.backend_url,
            pull=False,
        )
        agent = build_agent_config(
            state.runtime,
            selection,
            cwd=workspace,
            session_id=session_id,
            stream=stream,
            auto_confirm=technical_mode,
            confirm_callback=(lambda _tool, _summary: technical_mode),
        )
        answer = run_agent(prompt_for_model, selection, config=agent, messages=messages)
        return {
            "ok": True,
            "answer": answer,
            "session_id": session_id,
            "model": selection.ollama_tag,
            "display_name": selection.display_name,
        }
    except LLMError as exc:
        return {"ok": False, "error": exc.user_message, "session_id": session_id}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "session_id": session_id}


def _normalize_attachments(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    attachments: list[dict[str, str]] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        name = str(item.get("name") or Path(path).name).strip() or Path(path).name
        if path:
            attachments.append({"name": name, "path": path})
    return attachments


def _prompt_with_uploaded_files(
    prompt: str,
    workspace: str,
    attachments: list[dict[str, str]],
) -> str:
    if not attachments:
        return prompt

    blocks: list[str] = []
    for file in attachments:
        path = file["path"]
        if not _is_upload_path(path):
            blocks.append(
                f"### {file['name']}\n"
                f"Error: archivo adjunto rechazado porque no está en `{UPLOAD_DIR_NAME}/`."
            )
            continue
        content = read_document(workspace, path)
        if content.startswith("Error: formato no soportado"):
            content = read_file(workspace, path)
        if content.startswith("Error:"):
            blocks.append(
                f"### {file['name']}\n"
                f"Ruta local: {path}\n"
                f"No se pudo leer el archivo adjunto: {content}\n"
                "Explica este problema al usuario y pide que instale las dependencias "
                "o suba un PDF con texto extraible."
            )
            continue
        blocks.append(
            f"### {file['name']}\n"
            f"Ruta local: {path}\n"
            f"Contenido leído con read_document:\n{content}"
        )

    return (
        f"{prompt}\n\n"
        "Archivos adjuntos ya leídos localmente por Ci2Lab con read_document. "
        "Responde usando el contenido siguiente; no digas que no puedes acceder a los archivos.\n\n"
        + "\n\n".join(blocks)
    )


def _is_upload_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return normalized == UPLOAD_DIR_NAME or normalized.startswith(f"{UPLOAD_DIR_NAME}/")


def _upload_file(state: UIState, payload: dict[str, Any]) -> dict[str, Any]:
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    name = str(payload.get("name") or "").strip()
    encoded = str(payload.get("content_base64") or "").strip()
    if not name:
        return {"ok": False, "error": "Falta el nombre del archivo."}
    if not encoded:
        return {"ok": False, "error": "Falta el contenido del archivo."}

    safe_name = _safe_upload_name(name)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        return {
            "ok": False,
            "error": f"Formato no soportado. Usa uno de estos: {allowed}",
        }

    if "," in encoded and encoded.lower().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "El archivo no llegó con un contenido válido."}

    if len(raw) > MAX_UPLOAD_BYTES:
        return {
            "ok": False,
            "error": f"El archivo supera el límite de {_format_upload_size(MAX_UPLOAD_BYTES)}.",
        }

    base = Path(workspace or os.getcwd()).resolve()
    upload_dir = base / UPLOAD_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_upload_path(upload_dir, safe_name)
    if is_sensitive_path(target):
        return {
            "ok": False,
            "error": "No se admiten nombres que parezcan contener secretos, tokens o credenciales.",
        }

    target.write_bytes(raw)
    rel_path = target.relative_to(base).as_posix()
    return {
        "ok": True,
        "file": {
            "name": target.name,
            "path": rel_path,
            "size": len(raw),
            "size_label": _format_upload_size(len(raw)),
        },
    }


def _safe_upload_name(name: str) -> str:
    raw = Path(name).name.strip().replace("\x00", "")
    stem = Path(raw).stem[:90] or "archivo"
    suffix = Path(raw).suffix[:16]
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._-") or "archivo"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    return f"{safe_stem}{safe_suffix}".lower()


def _unique_upload_path(upload_dir: Path, safe_name: str) -> Path:
    candidate = upload_dir / safe_name
    if not candidate.exists():
        return candidate
    path = Path(safe_name)
    stem = path.stem or "archivo"
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = upload_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return upload_dir / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _format_upload_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _save_pending_session(
    *,
    session_id: str,
    messages: list[dict[str, Any]] | None,
    prompt: str,
    model_tag: str,
    cwd: str,
) -> None:
    try:
        history = list(messages or [])
        if not history or history[-1].get("role") != "user" or history[-1].get("content") != prompt:
            history.append({"role": "user", "content": prompt})
        save_session(session_id, messages=history, model_tag=model_tag, cwd=cwd)
    except Exception:  # noqa: BLE001
        return


def _save_completed_session(
    *,
    session_id: str,
    messages: list[dict[str, Any]] | None,
    prompt: str,
    answer: str,
    model_tag: str,
    cwd: str,
) -> None:
    try:
        history = list(messages or [])
        if not history or history[-1].get("role") != "user" or history[-1].get("content") != prompt:
            history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": answer})
        save_session(session_id, messages=history, model_tag=model_tag, cwd=cwd)
    except Exception:  # noqa: BLE001
        return


def _sessions_payload() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in list_sessions():
        session_id = str(row.get("id") or "")
        data = load_session(session_id) if session_id else None
        enriched = dict(row)
        enriched["internal_tag"] = session_id
        enriched["title"] = _session_title(data.get("messages", []) if data else [])
        rows.append(enriched)
    return rows


def _session_payload(session_id: str) -> tuple[dict[str, Any], int]:
    if not session_id or not all(ch.isalnum() or ch in "-_" for ch in session_id):
        return {"ok": False, "error": "Sesion no valida."}, 400
    data = load_session(session_id)
    if not data:
        return {"ok": False, "error": "Sesion no encontrada."}, 404

    messages = []
    for message in data.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = _message_text(message.get("content"))
        if role in {"user", "assistant", "system"} and content:
            messages.append({"role": role, "content": content})
    return {
        "ok": True,
        "session": {
            "id": data.get("id", session_id),
            "internal_tag": data.get("id", session_id),
            "title": _session_title(data.get("messages", [])),
            "model": data.get("model_tag", "?"),
            "cwd": data.get("cwd", "?"),
            "updated_at": data.get("updated_at", "?"),
            "messages": messages,
        },
    }, 200


def _delete_session_payload(session_id: str) -> tuple[dict[str, Any], int]:
    if not session_id or not all(ch.isalnum() or ch in "-_" for ch in session_id):
        return {"ok": False, "error": "Sesion no valida."}, 400
    deleted = delete_session(session_id)
    if not deleted:
        return {"ok": False, "error": "Sesion no encontrada."}, 404
    return {"ok": True, "session_id": session_id}, 200


def _session_title(messages: list[dict[str, Any]]) -> str:
    text = ""
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _message_text(message.get("content")).strip()
        if text:
            break
    if not text:
        return "Conversación"

    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", text)
    if not words:
        return "Conversación"

    stopwords = {
        "a", "al", "and", "are", "can", "como", "con", "de", "del", "do", "el",
        "en", "es", "este", "for", "haz", "how", "i", "is", "it", "la", "las",
        "le", "lo", "los", "me", "mi", "of", "para", "please", "por", "puedes",
        "que", "read", "se", "sobre", "the", "this", "to", "un", "una", "what",
        "where", "you",
    }
    keywords = [word for word in words if word.lower() not in stopwords]
    chosen = (keywords or words)[:4]
    title = " ".join(chosen).strip()
    if len(title) > 48:
        title = f"{title[:45].rstrip()}..."
    return title[:1].upper() + title[1:] if title else "Conversación"


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _pull_model(state: UIState, payload: dict[str, Any]) -> dict[str, Any]:
    tag = str(payload.get("tag") or "").strip()
    if not tag:
        return {"ok": False, "error": "Falta el tag de Ollama."}

    with state.pull_lock:
        for existing in state.pull_tasks.values():
            if existing["tag"] == tag and not existing["done"]:
                return {
                    "ok": True,
                    "tag": tag,
                    "task_id": existing["id"],
                    "task": _public_pull_task(existing),
                }

        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "tag": tag,
            "status": "Preparando descarga",
            "completed": 0,
            "total": 0,
            "percent": 0.0,
            "done": False,
            "ok": None,
            "error": None,
            "layers": {},
        }
        state.pull_tasks[task_id] = task

    thread = threading.Thread(
        target=_run_pull_task,
        args=(state, task_id, tag),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "tag": tag, "task_id": task_id, "task": _public_pull_task(task)}


def _pull_task_payload(state: UIState, task_id: str) -> tuple[dict[str, Any], int]:
    if not task_id or not all(ch.isalnum() or ch in "-_" for ch in task_id):
        return {"ok": False, "error": "Tarea no valida."}, 400
    with state.pull_lock:
        task = state.pull_tasks.get(task_id)
        if task is None:
            return {"ok": False, "error": "Tarea no encontrada."}, 404
        return {"ok": True, "task": _public_pull_task(task)}, 200


def _run_pull_task(state: UIState, task_id: str, tag: str) -> None:
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "POST",
                f"{state.ollama_base_url}/api/pull",
                json={"name": tag, "stream": True},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        _record_pull_event(state, task_id, event)

        _finish_pull_task(state, task_id, ok=True, status="Descarga completada")
    except Exception as exc:  # noqa: BLE001
        _finish_pull_task(state, task_id, ok=False, status="Error en la descarga", error=str(exc))


def _record_pull_event(state: UIState, task_id: str, event: dict[str, Any]) -> None:
    status = str(event.get("status") or "").strip()
    digest = str(event.get("digest") or "").strip()
    total = _safe_int(event.get("total"))
    completed = _safe_int(event.get("completed"))

    with state.pull_lock:
        task = state.pull_tasks.get(task_id)
        if task is None:
            return
        if status:
            task["status"] = status
        if digest and total:
            layers = task.setdefault("layers", {})
            layer = layers.setdefault(digest, {"completed": 0, "total": total})
            layer["total"] = max(total, layer.get("total", 0))
            layer["completed"] = max(completed, layer.get("completed", 0))
            _recompute_pull_totals(task)
        elif total:
            task["total"] = total
            task["completed"] = max(completed, task.get("completed", 0))
            task["percent"] = _pull_percent(task["completed"], task["total"])

        if status.lower() == "success":
            task["done"] = True
            task["ok"] = True
            task["status"] = "Descarga completada"
            task["percent"] = 100.0


def _finish_pull_task(
    state: UIState,
    task_id: str,
    *,
    ok: bool,
    status: str,
    error: str | None = None,
) -> None:
    with state.pull_lock:
        task = state.pull_tasks.get(task_id)
        if task is None:
            return
        task["done"] = True
        task["ok"] = ok
        task["status"] = status
        task["error"] = error
        if ok:
            task["percent"] = 100.0


def _recompute_pull_totals(task: dict[str, Any]) -> None:
    layers = task.get("layers") or {}
    total = 0
    completed = 0
    for layer in layers.values():
        layer_total = _safe_int(layer.get("total"))
        layer_completed = _safe_int(layer.get("completed"))
        total += layer_total
        completed += min(layer_completed, layer_total) if layer_total else layer_completed
    task["total"] = total
    task["completed"] = completed
    task["percent"] = _pull_percent(completed, total)


def _pull_percent(completed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(99.0, completed / total * 100)), 1)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _public_pull_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "tag": task["tag"],
        "status": task["status"],
        "completed": task["completed"],
        "total": task["total"],
        "percent": task["percent"],
        "done": task["done"],
        "ok": task["ok"],
        "error": task["error"],
    }


def _delete_model(state: UIState, payload: dict[str, Any]) -> dict[str, Any]:
    tag = str(payload.get("tag") or "").strip()
    if not tag:
        return {"ok": False, "error": "Falta el tag de Ollama."}

    with state.delete_lock:
        for existing in state.delete_tasks.values():
            if existing["tag"] == tag and not existing["done"]:
                return {
                    "ok": True,
                    "tag": tag,
                    "task_id": existing["id"],
                    "task": _public_delete_task(existing),
                }

        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "tag": tag,
            "status": "Preparando desinstalación",
            "percent": 8.0,
            "done": False,
            "ok": None,
            "error": None,
        }
        state.delete_tasks[task_id] = task

    thread = threading.Thread(
        target=_run_delete_task,
        args=(state, task_id, tag),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "tag": tag, "task_id": task_id, "task": _public_delete_task(task)}


def _delete_task_payload(state: UIState, task_id: str) -> tuple[dict[str, Any], int]:
    if not task_id or not all(ch.isalnum() or ch in "-_" for ch in task_id):
        return {"ok": False, "error": "Tarea no valida."}, 400
    with state.delete_lock:
        task = state.delete_tasks.get(task_id)
        if task is None:
            return {"ok": False, "error": "Tarea no encontrada."}, 404
        return {"ok": True, "task": _public_delete_task(task)}, 200


def _run_delete_task(state: UIState, task_id: str, tag: str) -> None:
    try:
        _update_delete_task(state, task_id, status="Contactando con Ollama", percent=35.0)
        with httpx.Client(timeout=60.0) as client:
            _update_delete_task(state, task_id, status="Eliminando modelo local", percent=65.0)
            response = client.request(
                "DELETE",
                f"{state.ollama_base_url}/api/delete",
                json={"name": tag},
            )
            response.raise_for_status()
        _finish_delete_task(state, task_id, ok=True, status="Modelo desinstalado")
    except Exception as exc:  # noqa: BLE001
        _finish_delete_task(state, task_id, ok=False, status="Error al desinstalar", error=str(exc))


def _update_delete_task(state: UIState, task_id: str, *, status: str, percent: float) -> None:
    with state.delete_lock:
        task = state.delete_tasks.get(task_id)
        if task is None:
            return
        task["status"] = status
        task["percent"] = max(task.get("percent", 0.0), percent)


def _finish_delete_task(
    state: UIState,
    task_id: str,
    *,
    ok: bool,
    status: str,
    error: str | None = None,
) -> None:
    with state.delete_lock:
        task = state.delete_tasks.get(task_id)
        if task is None:
            return
        task["done"] = True
        task["ok"] = ok
        task["status"] = status
        task["error"] = error
        task["percent"] = 100.0 if ok else task.get("percent", 0.0)


def _public_delete_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "tag": task["tag"],
        "status": task["status"],
        "percent": task["percent"],
        "done": task["done"],
        "ok": task["ok"],
        "error": task["error"],
    }


def _list_runs(runs_dir: str) -> list[dict[str, Any]]:
    base = Path(runs_dir)
    if not base.is_dir():
        return []
    rows = []
    for path in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        if path.is_dir():
            rows.append({
                "name": path.name,
                "path": str(path),
                "modified": path.stat().st_mtime,
            })
    return rows


def _content_type(name: str) -> str:
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".css"):
        return "text/css; charset=utf-8"
    if name.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if name.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"
