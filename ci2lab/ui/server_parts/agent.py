"""Agent execution flow used by the UI chat endpoint."""

from __future__ import annotations

import os
from typing import Any

from ci2lab.harness.llm_errors import LLMCancelledError, LLMError
from ci2lab.harness.multiagent.manuscript import build_index
from ci2lab.harness.multiagent.paper_review import ReviewContext
from ci2lab.harness.session import load_session, new_session_id, save_session
from ci2lab.harness.token_usage import TokenUsageState
from ci2lab.router.catalog import find_model_by_tag
from ci2lab.runtime.ollama import is_catalog_model_installed
from ci2lab.ui.projects import (
    get_project,
    project_dir,
    project_manuscript_text,
    project_prompt,
)
from ci2lab.ui.researchers import get_researcher, researcher_context_block
from ci2lab.ui.server_parts.uploads import normalize_attachments, prompt_with_uploaded_files


class ChatCancelled(RuntimeError):
    """Raised when the web UI asks an in-flight chat request to stop."""


def chat(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("message") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Type a message before sending."}

    model_result = resolve_selected_installed_model(state, payload)
    if not model_result["ok"]:
        return model_result
    model = str(model_result["model"])
    project_id = str(payload.get("project_id") or "").strip()
    project = get_project(project_id) if project_id else None
    if project_id and project is None:
        return {"ok": False, "error": "The selected project no longer exists."}
    workspace = (
        str(project_dir(project_id))
        if project
        else str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    )
    attachments = normalize_attachments(payload.get("attachments"))
    prompt_for_model = prompt_with_uploaded_files(prompt, workspace, attachments)
    if project:
        prompt_for_model = project_prompt(project_id, prompt_for_model)

    # Researcher profile: adapt the review's field/style (it never licenses
    # inventing content). Peer-review mode is requested explicitly or implied by
    # a paper-review project.
    researcher_id = str(payload.get("researcher_id") or "").strip()
    reviewer_profile = get_researcher(researcher_id) if researcher_id else None
    reviewer_block = researcher_context_block(reviewer_profile) if reviewer_profile else ""
    mode = str(payload.get("mode") or "").strip().lower()
    paper_review_mode = mode == "paper_review" or bool(
        project and project.get("kind") == "paper_review"
    )

    review_context = None
    if paper_review_mode and project:
        raw_text, source_name = project_manuscript_text(project_id)
        review_context = ReviewContext(
            index=build_index(raw_text),
            paper_meta={
                "paper_title": project.get("paper_title") or project.get("name"),
                "field": project.get("field"),
                "target_venue": project.get("target_venue"),
                "article_type": project.get("article_type"),
            },
            reviewer_block=reviewer_block,
            manuscript_source_name=source_name,
        )
    elif reviewer_block:
        # A reviewer profile still colors ordinary chats / generic multi-agent runs.
        prompt_for_model = f"{prompt_for_model}\n\n{reviewer_block}"

    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    stream = bool(payload.get("stream", False))
    # Peer review is inherently the multi-agent grounded flow.
    multi_agent = bool(payload.get("multi_agent", False)) or paper_review_mode
    request_id = str(payload.get("request_id") or "").strip()
    cancellation_event = state.begin_chat_request(request_id) if request_id else None
    progress_events: list[str] = []

    def record_progress(message: str) -> None:
        if cancellation_event and cancellation_event.is_set():
            raise ChatCancelled()
        message = str(message or "").strip()
        if message:
            progress_events.append(message)

    loaded = load_session(session_id)
    loaded_project_id = str((loaded or {}).get("project_id") or "").strip()
    if loaded and loaded_project_id != project_id:
        return {
            "ok": False,
            "error": (
                "This conversation belongs to a different project. "
                "Open it from that project or start a new conversation."
            ),
            "session_id": session_id,
            "project_id": project_id or None,
        }
    messages = loaded.get("messages") if loaded else None
    existing_token_usage = loaded.get("token_usage") if loaded else None
    save_pending_session(
        session_id=session_id,
        messages=messages,
        prompt=prompt,
        model_tag=model,
        cwd=workspace,
        token_usage=existing_token_usage,
        project_id=project_id or None,
    )

    try:
        prepare_session, build_agent_config, run_agent, run_multi_agent = _agent_dependencies()
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
        agent.cancellation_event = cancellation_event
        agent.project_id = project_id or None
        agent.researcher_id = researcher_id or None
        agent.multiagent_flow = "paper_review" if paper_review_mode else None
        if multi_agent:
            # Only forward review_context on the paper-review path so the generic
            # multi-agent call signature stays unchanged for everything else.
            review_kwargs = (
                {"review_context": review_context} if review_context is not None else {}
            )
            answer = _call_with_optional_progress(
                run_multi_agent,
                prompt_for_model,
                selection,
                config=agent,
                on_progress=record_progress,
                **review_kwargs,
            )
            save_completed_session(
                session_id=session_id,
                messages=messages,
                prompt=prompt,
                answer=answer,
                model_tag=selection.ollama_tag,
                cwd=workspace,
                token_usage=agent.token_usage.to_dict(),
                project_id=project_id or None,
            )
        else:
            answer = run_agent(
                prompt_for_model,
                selection,
                config=agent,
                messages=messages,
                on_progress=record_progress,
            )
            # Project source excerpts are retrieval context, not user-authored
            # conversation. Persist a clean visible turn so repeated project
            # queries do not accumulate copied source text in session history.
            if project:
                save_completed_session(
                    session_id=session_id,
                    messages=messages,
                    prompt=prompt,
                    answer=answer,
                    model_tag=selection.ollama_tag,
                    cwd=workspace,
                    token_usage=agent.token_usage.to_dict(),
                    project_id=project_id,
                )
        return {
            "ok": True,
            "answer": answer,
            "session_id": session_id,
            "model": selection.ollama_tag,
            "display_name": selection.display_name,
            "multi_agent": multi_agent,
            "paper_review": paper_review_mode,
            "usage": agent.token_usage.to_dict(),
            "process_log": progress_events,
            "project_id": project_id or None,
            "researcher_id": researcher_id or None,
        }
    except (ChatCancelled, LLMCancelledError):
        return {
            "ok": False,
            "cancelled": True,
            "error": "Stopped by the user.",
            "session_id": session_id,
            "process_log": progress_events,
        }
    except LLMError as exc:
        return {
            "ok": False,
            "error": exc.user_message,
            "session_id": session_id,
            "process_log": progress_events,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "session_id": session_id,
            "process_log": progress_events,
        }
    finally:
        if request_id:
            state.finish_chat_request(request_id)


def chat_cancel(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        return {"ok": False, "error": "Missing request id."}
    return {"ok": True, "cancelled": state.cancel_chat_request(request_id)}


def chat_start(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    model_result = resolve_selected_installed_model(state, payload)
    if not model_result["ok"]:
        return model_result
    model = str(model_result["model"])
    project_id = str(payload.get("project_id") or "").strip()
    project = get_project(project_id) if project_id else None
    if project_id and project is None:
        return {"ok": False, "error": "The selected project no longer exists."}
    workspace = (
        str(project_dir(project_id))
        if project
        else str(payload.get("workspace") or state.runtime.workspace or os.getcwd())
    )
    session_id = str(payload.get("session_id") or "").strip() or new_session_id()
    researcher_id = str(payload.get("researcher_id") or "").strip()
    mode = str(payload.get("mode") or "").strip().lower()
    paper_review_mode = mode == "paper_review" or bool(
        project and project.get("kind") == "paper_review"
    )
    multi_agent = bool(payload.get("multi_agent", False)) or paper_review_mode
    warnings: list[str] = []

    try:
        prepare_session, _build_agent_config, _run_agent, _run_multi_agent = _agent_dependencies()
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
        "ui_mode": "multi_agent" if multi_agent else "herramientas_activas",
        "multi_agent": multi_agent,
        "paper_review": paper_review_mode,
        "security_profile": state.runtime.security.profile,
        "security_engine": state.runtime.security.engine,
        "warnings": warnings,
        "usage": TokenUsageState().to_dict(),
        "project_id": project_id or None,
        "project_name": project["name"] if project else None,
        "researcher_id": researcher_id or None,
    }


def save_pending_session(
    *,
    session_id: str,
    messages: list[dict[str, Any]] | None,
    prompt: str,
    model_tag: str,
    cwd: str,
    token_usage: dict[str, Any] | None = None,
    project_id: str | None = None,
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
            project_id=project_id,
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
    project_id: str | None = None,
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
            project_id=project_id,
        )
    except Exception:  # noqa: BLE001
        return


def _agent_dependencies():
    from ci2lab.ui import server as facade

    return (
        facade.prepare_session,
        facade.build_agent_config,
        facade.run_agent,
        facade.run_multi_agent,
    )


def _call_with_optional_progress(func: Any, *args: Any, on_progress: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, on_progress=on_progress, **kwargs)
    except TypeError as exc:
        if "on_progress" not in str(exc):
            raise
        return func(*args, **kwargs)


def resolve_selected_installed_model(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    selected = str(payload.get("model") or "").strip()
    if not selected:
        return {
            "ok": False,
            "error": (
                "Select an installed model before chatting. "
                "If none appears, download one in Local models."
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
            "error": f"Could not check Ollama or its installed models: {error}",
            "model": model_tag,
            "display_name": display_name,
            "usage": TokenUsageState().to_dict(),
        }
    installed_names = {str(item.get("name") or "") for item in installed}
    if not is_catalog_model_installed(model_tag, installed_names):
        return {
            "ok": False,
            "error": (
                f"The selected model is not installed: {model_tag}. "
                "Choose an installed model from the dropdown or download it in Local models."
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
