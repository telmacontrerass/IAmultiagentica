"""Local-only HTTP server facade for the Ci2Lab web UI."""

from __future__ import annotations

from ci2lab.harness import run_agent
from ci2lab.harness.multiagent import run_multi_agent
from ci2lab.harness.tools.filesystem import read_document, read_file
from ci2lab.hardware import scan_hardware
from ci2lab.pipeline import build_agent_config, prepare_session
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.recommend import (
    build_display_recommendations,
    recommendation_pool_size,
    score_recommendations,
)
from ci2lab.ui.server_parts.agent import (
    chat as _chat,
    chat_cancel as _chat_cancel,
    chat_start as _chat_start,
    save_completed_session as _save_completed_session,
    save_pending_session as _save_pending_session,
)
from ci2lab.ui.server_parts.api import (
    UI_ACTIONS,
    delete_model as _delete_model,
    delete_task_payload as _delete_task_payload,
    finish_delete_task as _finish_delete_task,
    finish_pull_task as _finish_pull_task,
    health_payload as _health_payload,
    models_payload as _models_payload,
    pull_model as _pull_model,
    pull_percent as _pull_percent,
    pull_task_payload as _pull_task_payload,
    record_pull_event as _record_pull_event,
    recompute_pull_totals as _recompute_pull_totals,
    run_delete_task as _run_delete_task,
    run_pull_task as _run_pull_task,
    system_payload as _system_payload,
    tool_group as _tool_group,
    tool_web_status as _tool_web_status,
    tools_payload as _tools_payload,
    update_delete_task as _update_delete_task,
)
from ci2lab.ui.server_parts.http import (
    UIState,
    content_type_for as _content_type,
    handler_factory as _handler_factory,
    run_ui,
)
from ci2lab.ui.server_parts.serializers import (
    bytes_to_gb as _bytes_to_gb,
    delete_session_payload as _delete_session_payload,
    disk_payload as _disk_payload,
    format_upload_size as _format_upload_size,
    list_runs as _list_runs,
    message_text as _message_text,
    public_delete_task as _public_delete_task,
    public_pull_task as _public_pull_task,
    safe_int as _safe_int,
    session_payload as _session_payload,
    session_title as _session_title,
    sessions_payload as _sessions_payload,
)
from ci2lab.ui.server_parts.uploads import (
    DOCUMENT_UPLOAD_SUFFIXES,
    MAX_UPLOAD_BYTES,
    SUPPORTED_UPLOAD_SUFFIXES,
    UPLOAD_DIR_NAME,
    is_upload_path as _is_upload_path,
    normalize_attachments as _normalize_attachments,
    prompt_with_uploaded_files as _prompt_with_uploaded_files,
    safe_upload_name as _safe_upload_name,
    unique_upload_path as _unique_upload_path,
    upload_file as _upload_file,
)
from ci2lab.ui.projects import (
    add_project_source as _add_project_source,
    create_project as _create_project,
    delete_project as _delete_project,
    delete_project_source as _delete_project_source,
    get_project as _get_project,
    list_project_sources as _list_project_sources,
    list_projects as _list_projects,
    project_manuscript_text as _project_manuscript_text,
    project_prompt as _project_prompt,
    rename_project as _rename_project,
    update_project_metadata as _update_project_metadata,
)
from ci2lab.ui.researchers import (
    create_researcher as _create_researcher,
    delete_researcher as _delete_researcher,
    get_researcher as _get_researcher,
    list_researchers as _list_researchers,
    update_researcher as _update_researcher,
)

__all__ = [
    "DOCUMENT_UPLOAD_SUFFIXES",
    "MAX_UPLOAD_BYTES",
    "SUPPORTED_UPLOAD_SUFFIXES",
    "UIState",
    "UI_ACTIONS",
    "UPLOAD_DIR_NAME",
    "run_ui",
]
