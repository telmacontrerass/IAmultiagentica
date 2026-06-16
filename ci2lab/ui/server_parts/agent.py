"""Agent execution flow used by the UI chat endpoint."""

from __future__ import annotations

import os
from typing import Any

from ci2lab.harness.document_answer import maybe_answer_document_request
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.session import load_session, new_session_id, save_session
from ci2lab.harness.token_usage import TokenUsageState
from ci2lab.router.catalog import find_model_by_tag
from ci2lab.runtime.ollama import is_catalog_model_installed
from ci2lab.ui.server_parts.uploads import normalize_attachments, prompt_with_uploaded_files


def chat(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("message") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Escribe un mensaje antes de enviar."}

    model_result = resolve_selected_installed_model(state, payload)
    if not model_result["ok"]:
        return model_result
    model = str(model_result["model"])
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    attachments = normalize_attachments(payload.get("attachments"))
    prompt_for_model = prompt_with_uploaded_files(prompt, workspace, attachments)
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    stream = bool(payload.get("stream", False))
    loaded = load_session(session_id)
    messages = loaded.get("messages") if loaded else None
    existing_token_usage = loaded.get("token_usage") if loaded else None
    save_pending_session(
        session_id=session_id,
        messages=messages,
        prompt=prompt,
        model_tag=model,
        cwd=workspace,
        token_usage=existing_token_usage,
    )
    direct_answer = (
        maybe_answer_document_request(prompt, [prompt_for_model])
        if attachments
        else None
    )
    if direct_answer:
        save_completed_session(
            session_id=session_id,
            messages=messages,
            prompt=prompt,
            answer=direct_answer,
            model_tag=model,
            cwd=workspace,
            token_usage=existing_token_usage,
        )
        usage_state = TokenUsageState()
        usage_state.hydrate_session(existing_token_usage)
        return {
            "ok": True,
            "answer": direct_answer,
            "session_id": session_id,
            "model": model,
            "display_name": model,
            "usage": usage_state.to_dict(),
        }

    try:
        prepare_session, build_agent_config, run_agent = _agent_dependencies()
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
            auto_confirm=True,
            confirm_callback=(lambda _tool, _summary: True),
        )
        answer = run_agent(prompt_for_model, selection, config=agent, messages=messages)
        return {
            "ok": True,
            "answer": answer,
            "session_id": session_id,
            "model": selection.ollama_tag,
            "display_name": selection.display_name,
            "usage": agent.token_usage.to_dict(),
        }
    except LLMError as exc:
        return {"ok": False, "error": exc.user_message, "session_id": session_id}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "session_id": session_id}


def chat_start(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    model_result = resolve_selected_installed_model(state, payload)
    if not model_result["ok"]:
        return model_result
    model = str(model_result["model"])
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    warnings: list[str] = []

    try:
        prepare_session, _build_agent_config, _run_agent = _agent_dependencies()
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
        "ui_mode": "herramientas_activas",
        "security_profile": state.runtime.security.profile,
        "security_engine": state.runtime.security.engine,
        "warnings": warnings,
        "usage": TokenUsageState().to_dict(),
    }


def save_pending_session(
    *,
    session_id: str,
    messages: list[dict[str, Any]] | None,
    prompt: str,
    model_tag: str,
    cwd: str,
    token_usage: dict[str, Any] | None = None,
) -> None:
    try:
        history = list(messages or [])
        if not history or history[-1].get("role") != "user" or history[-1].get("content") != prompt:
            history.append({"role": "user", "content": prompt})
        save_session(
            session_id,
            messages=history,
            model_tag=model_tag,
            cwd=cwd,
            token_usage=token_usage,
        )
    except Exception:  # noqa: BLE001
        return


def save_completed_session(
    *,
    session_id: str,
    messages: list[dict[str, Any]] | None,
    prompt: str,
    answer: str,
    model_tag: str,
    cwd: str,
    token_usage: dict[str, Any] | None = None,
) -> None:
    try:
        history = list(messages or [])
        if not history or history[-1].get("role") != "user" or history[-1].get("content") != prompt:
            history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": answer})
        save_session(
            session_id,
            messages=history,
            model_tag=model_tag,
            cwd=cwd,
            token_usage=token_usage,
        )
    except Exception:  # noqa: BLE001
        return


def _agent_dependencies():
    from ci2lab.ui import server as facade

    return facade.prepare_session, facade.build_agent_config, facade.run_agent


def resolve_selected_installed_model(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    selected = str(payload.get("model") or "").strip()
    if not selected:
        return {
            "ok": False,
            "error": (
                "Selecciona un modelo instalado antes de chatear. "
                "Si no aparece ninguno, descarga uno en Modelos locales."
            ),
            "usage": TokenUsageState().to_dict(),
        }

    spec = find_model_by_tag(selected)
    model_tag = spec.ollama_tag if spec else selected
    display_name = spec.display_name if spec else selected

    installed, error = state.list_installed_models()
    if error:
        return {
            "ok": False,
            "error": f"No se pudo comprobar Ollama ni sus modelos instalados: {error}",
            "model": model_tag,
            "display_name": display_name,
            "usage": TokenUsageState().to_dict(),
        }
    installed_names = {str(item.get("name") or "") for item in installed}
    if not is_catalog_model_installed(model_tag, installed_names):
        return {
            "ok": False,
            "error": (
                f"El modelo seleccionado no esta instalado: {model_tag}. "
                "Elige un modelo instalado en el desplegable o descargalo en Modelos locales."
            ),
            "model": model_tag,
            "display_name": display_name,
            "usage": TokenUsageState().to_dict(),
        }

    return {
        "ok": True,
        "model": model_tag,
        "display_name": display_name,
    }
