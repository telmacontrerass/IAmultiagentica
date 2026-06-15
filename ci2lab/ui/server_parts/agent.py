"""Agent execution flow used by the UI chat endpoint."""

from __future__ import annotations

import os
from typing import Any

from ci2lab.harness.document_answer import maybe_answer_document_request
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.session import load_session, new_session_id, save_session
from ci2lab.ui.server_parts.uploads import normalize_attachments, prompt_with_uploaded_files


def chat(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("message") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Escribe un mensaje antes de enviar."}

    model = str(payload.get("model") or state.runtime.model).strip()
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    attachments = normalize_attachments(payload.get("attachments"))
    prompt_for_model = prompt_with_uploaded_files(prompt, workspace, attachments)
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    technical_mode = bool(payload.get("technical_mode"))
    stream = bool(payload.get("stream", False))
    loaded = load_session(session_id)
    messages = loaded.get("messages") if loaded else None
    save_pending_session(
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
        save_completed_session(
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


def chat_start(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    model = str(payload.get("model") or state.runtime.model).strip()
    workspace = str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    technical_mode = bool(payload.get("technical_mode"))
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
        "ui_mode": "tecnico" if technical_mode else "protegido",
        "security_profile": state.runtime.security.profile,
        "security_engine": state.runtime.security.engine,
        "warnings": warnings,
    }


def save_pending_session(
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


def save_completed_session(
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


def _agent_dependencies():
    from ci2lab.ui import server as facade

    return facade.prepare_session, facade.build_agent_config, facade.run_agent
