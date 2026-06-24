"""API payload builders and background model tasks for the web UI."""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any

import httpx

from ci2lab.harness.mcp.config import load_mcp_config
from ci2lab.harness.permissions import CONFIRM_TOOLS
from ci2lab.harness.skills.loader import load_skills
from ci2lab.harness.tools.registry import FUNCTION_SCHEMAS
from ci2lab.runtime.ollama import is_catalog_model_installed, ollama_install_info
from ci2lab.ui.server_parts.serializers import (
    disk_payload,
    list_runs,
    public_delete_task,
    public_pull_task,
    safe_int,
    session_payload,
    sessions_payload,
)
from ci2lab.ui.server_parts.uploads import DOCUMENT_UPLOAD_SUFFIXES, SUPPORTED_UPLOAD_SUFFIXES

# NOTE: "id", "tool" and "group" are wire/identifier values. "group" shares the
# vocabulary returned by tool_group() below, which the frontend (app.js groupNames)
# matches verbatim, so the group labels must stay consistent across both files.
UI_ACTIONS: list[dict[str, str]] = [
    {
        "id": "read_document",
        "label": "Summarize attachment",
        "tool": "read_document",
        "group": "Documents",
        "prompt": "Read and summarize the attached files. Extract key ideas and actionable points.",
    },
    {
        "id": "workspace_tree",
        "label": "Project map",
        "tool": "tree",
        "group": "Explore",
        "prompt": "Make a brief map of the project using tree, file_info and read_file only when needed.",
    },
    {
        "id": "search_workspace",
        "label": "Search in files",
        "tool": "grep",
        "group": "Explore",
        "prompt": "Search the workspace for the text or concept I give you and tell me which files it appears in.",
    },
    {
        "id": "git_status",
        "label": "Git status",
        "tool": "git_status",
        "group": "Git",
        "prompt": "Show the git status of the workspace and summarize the pending changes.",
    },
    {
        "id": "git_diff",
        "label": "Review diff",
        "tool": "git_diff",
        "group": "Git",
        "prompt": "Review the current git diff. Point out risks, logical conflicts and recommended tests.",
    },
    {
        "id": "todo_plan",
        "label": "Task plan",
        "tool": "todo_write",
        "group": "Planning",
        "prompt": "Create or update a task list for this work using todo_write.",
    },
    {
        "id": "web_reference",
        "label": "Look up URL",
        "tool": "web_fetch",
        "group": "Web",
        "prompt": "Look up this URL with web_fetch and summarize what matters: https://",
    },
    {
        "id": "notebook_edit",
        "label": "Edit notebook",
        "tool": "notebook_edit",
        "group": "Notebook",
        "prompt": "Edit the given notebook with notebook_edit. Path, cell and content:",
    },
    {
        "id": "skill",
        "label": "Use skill",
        "tool": "skill",
        "group": "Skills",
        "prompt": "If there is a suitable skill, invoke it with the skill tool and follow its instructions.",
    },
    {
        "id": "mcp_call",
        "label": "Use MCP",
        "tool": "mcp_call",
        "group": "MCP",
        "prompt": "Use a configured MCP tool if it fits. Server, tool and arguments:",
    },
]


def health_payload(state: Any) -> dict[str, Any]:
    installed, error = state.list_installed_models()
    install_info = ollama_install_info()
    return {
        "ok": error is None,
        "ollama_error": error,
        "ollama_base_url": state.ollama_base_url,
        "ollama_executable": install_info["executable"],
        "ollama_models_dir": install_info["models_dir"],
        "installed_count": len(installed),
        "workspace": state.runtime.workspace or os.getcwd(),
        "model": None,
        "runs_dir": state.runtime.runs_dir,
        "local_only": True,
    }


def models_payload(state: Any) -> dict[str, Any]:
    installed, error = state.list_installed_models()
    installed_names = {item["name"] for item in installed}
    profile = None
    try:
        profile = _facade().scan_hardware()
    except Exception:  # noqa: BLE001
        profile = None

    recommendations = {}
    if profile is not None:
        try:
            recommendations = {
                item.model.id: item
                for item in _facade().score_recommendations(
                    "",
                    profile=profile,
                    limit=len(_facade().load_model_catalog()),
                )
            }
        except Exception:  # noqa: BLE001
            recommendations = {}

    catalog = []
    for model in _facade().load_model_catalog():
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
            "context_length": model.context_length,
            "tool_mode": model.tool_mode,
            "supports_tools": model.supports_tools,
            "installed": is_catalog_model_installed(model.ollama_tag, installed_names),
            "fit_label": getattr(item, "fit_label", None),
            "recommendation_status": getattr(item, "recommendation_status", None),
        })
    return {
        "catalog": catalog,
        "installed": installed,
        "ollama_error": error,
    }


def system_payload(state: Any) -> dict[str, Any]:
    workspace = state.runtime.workspace or os.getcwd()
    try:
        profile = _facade().scan_hardware()
        installed_names = {item["name"] for item in state.list_installed_models()[0]}
        pool_limit = _facade().recommendation_pool_size(4)
        scored = _facade().score_recommendations("", profile=profile, limit=pool_limit)
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
            for entry in _facade().build_display_recommendations(
                scored,
                installed_names,
                limit=4,
            )
        ]
        return {
            "ok": True,
            "hardware": profile.to_dict(),
            "disk": disk_payload(workspace),
            "recommendations": recommendations,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "hardware": None,
            "disk": disk_payload(workspace),
            "recommendations": [],
        }


def tools_payload(state: Any) -> dict[str, Any]:
    workspace = str(state.runtime.workspace or os.getcwd())
    skills = load_skills(workspace)
    mcp_servers = load_mcp_config(workspace)
    tools = []
    for schema in FUNCTION_SCHEMAS:
        function = schema.get("function", {})
        name = str(function.get("name") or "")
        if not name:
            continue
        group = tool_group(name)
        tools.append({
            "name": name,
            "group": group,
            "description": str(function.get("description") or ""),
            "requires_confirmation": name in CONFIRM_TOOLS,
            "web_status": tool_web_status(name),
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


def tool_group(name: str) -> str:
    # Return values are wire-coupled: app.js (groupNames) matches these labels
    # verbatim to group the tools list, so keep both sides in sync.
    if name in {"read_document", "read_file", "ls", "grep", "glob", "file_info", "tree", "inspect_file"}:
        return "Explore"
    if name in {"write_file", "edit_file", "notebook_edit"}:
        return "Edit"
    if name in {"git_status", "git_diff"}:
        return "Git"
    if name in {"todo_write", "ask_user"}:
        return "Planning"
    if name == "web_fetch":
        return "Web"
    if name == "skill":
        return "Skills"
    if name == "mcp_call" or name.startswith("mcp__"):
        return "MCP"
    if name == "bash":
        return "System"
    return "Other"


def tool_web_status(name: str) -> str:
    if name == "ask_user":
        return "Terminal only; on the web it asks directly in the chat."
    if name in CONFIRM_TOOLS:
        return "Available from the chat with the same tool access as the CLI."
    return "Available from the chat."


def pull_model(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    tag = str(payload.get("tag") or "").strip()
    if not tag:
        return {"ok": False, "error": "The Ollama tag is missing."}

    with state.pull_lock:
        for existing in state.pull_tasks.values():
            if existing["tag"] == tag and not existing["done"]:
                return {
                    "ok": True,
                    "tag": tag,
                    "task_id": existing["id"],
                    "task": public_pull_task(existing),
                }

        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "tag": tag,
            "status": "Preparing download",
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
        target=run_pull_task,
        args=(state, task_id, tag),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "tag": tag, "task_id": task_id, "task": public_pull_task(task)}


def pull_task_payload(state: Any, task_id: str) -> tuple[dict[str, Any], int]:
    if not task_id or not all(ch.isalnum() or ch in "-_" for ch in task_id):
        return {"ok": False, "error": "Invalid task."}, 400
    with state.pull_lock:
        task = state.pull_tasks.get(task_id)
        if task is None:
            return {"ok": False, "error": "Task not found."}, 404
        return {"ok": True, "task": public_pull_task(task)}, 200


def run_pull_task(state: Any, task_id: str, tag: str) -> None:
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
                        record_pull_event(state, task_id, event)

        finish_pull_task(state, task_id, ok=True, status="Download complete")
    except Exception as exc:  # noqa: BLE001
        finish_pull_task(state, task_id, ok=False, status="Download error", error=str(exc))


def record_pull_event(state: Any, task_id: str, event: dict[str, Any]) -> None:
    status = str(event.get("status") or "").strip()
    digest = str(event.get("digest") or "").strip()
    total = safe_int(event.get("total"))
    completed = safe_int(event.get("completed"))

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
            recompute_pull_totals(task)
        elif total:
            task["total"] = total
            task["completed"] = max(completed, task.get("completed", 0))
            task["percent"] = pull_percent(task["completed"], task["total"])

        if status.lower() == "success":
            task["done"] = True
            task["ok"] = True
            task["status"] = "Download complete"
            task["percent"] = 100.0


def finish_pull_task(
    state: Any,
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


def recompute_pull_totals(task: dict[str, Any]) -> None:
    layers = task.get("layers") or {}
    total = 0
    completed = 0
    for layer in layers.values():
        layer_total = safe_int(layer.get("total"))
        layer_completed = safe_int(layer.get("completed"))
        total += layer_total
        completed += min(layer_completed, layer_total) if layer_total else layer_completed
    task["total"] = total
    task["completed"] = completed
    task["percent"] = pull_percent(completed, total)


def pull_percent(completed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(99.0, completed / total * 100)), 1)


def delete_model(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    tag = str(payload.get("tag") or "").strip()
    if not tag:
        return {"ok": False, "error": "The Ollama tag is missing."}

    with state.delete_lock:
        for existing in state.delete_tasks.values():
            if existing["tag"] == tag and not existing["done"]:
                return {
                    "ok": True,
                    "tag": tag,
                    "task_id": existing["id"],
                    "task": public_delete_task(existing),
                }

        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "tag": tag,
            "status": "Preparing uninstall",
            "percent": 8.0,
            "done": False,
            "ok": None,
            "error": None,
        }
        state.delete_tasks[task_id] = task

    thread = threading.Thread(
        target=run_delete_task,
        args=(state, task_id, tag),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "tag": tag, "task_id": task_id, "task": public_delete_task(task)}


def delete_task_payload(state: Any, task_id: str) -> tuple[dict[str, Any], int]:
    if not task_id or not all(ch.isalnum() or ch in "-_" for ch in task_id):
        return {"ok": False, "error": "Invalid task."}, 400
    with state.delete_lock:
        task = state.delete_tasks.get(task_id)
        if task is None:
            return {"ok": False, "error": "Task not found."}, 404
        return {"ok": True, "task": public_delete_task(task)}, 200


def run_delete_task(state: Any, task_id: str, tag: str) -> None:
    try:
        update_delete_task(state, task_id, status="Contacting Ollama", percent=35.0)
        with httpx.Client(timeout=60.0) as client:
            update_delete_task(state, task_id, status="Removing local model", percent=65.0)
            response = client.request(
                "DELETE",
                f"{state.ollama_base_url}/api/delete",
                json={"name": tag},
            )
            response.raise_for_status()
        finish_delete_task(state, task_id, ok=True, status="Model uninstalled")
    except Exception as exc:  # noqa: BLE001
        finish_delete_task(state, task_id, ok=False, status="Uninstall error", error=str(exc))


def update_delete_task(state: Any, task_id: str, *, status: str, percent: float) -> None:
    with state.delete_lock:
        task = state.delete_tasks.get(task_id)
        if task is None:
            return
        task["status"] = status
        task["percent"] = max(task.get("percent", 0.0), percent)


def finish_delete_task(
    state: Any,
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


def _facade():
    from ci2lab.ui import server as facade

    return facade

