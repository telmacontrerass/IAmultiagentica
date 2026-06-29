"""Local-only HTTP server facade for the Ci2Lab web UI."""

from __future__ import annotations

from ci2lab.hardware import scan_hardware
from ci2lab.harness import run_agent
from ci2lab.harness.multiagent import run_multi_agent
from ci2lab.harness.tools.filesystem import read_document, read_file
from ci2lab.pipeline import build_agent_config, prepare_session
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.recommend import (
    build_display_recommendations,
    recommendation_pool_size,
    score_recommendations,
)
from ci2lab.ui.projects import (
    add_project_source as _add_project_source,
)
from ci2lab.ui.projects import (
    create_project as _create_project,
)
from ci2lab.ui.projects import (
    delete_project as _delete_project,
)
from ci2lab.ui.projects import (
    delete_project_source as _delete_project_source,
)
from ci2lab.ui.projects import (
    get_project as _get_project,
)
from ci2lab.ui.projects import (
    list_project_sources as _list_project_sources,
)
from ci2lab.ui.projects import (
    list_projects as _list_projects,
)
from ci2lab.ui.projects import (
    project_artifact_path as _project_artifact_path,
)
from ci2lab.ui.projects import (
    project_manuscript_text as _project_manuscript_text,
)
from ci2lab.ui.projects import (
    project_prompt as _project_prompt,
)
from ci2lab.ui.projects import (
    rename_project as _rename_project,
)
from ci2lab.ui.projects import (
    update_project_metadata as _update_project_metadata,
)
from ci2lab.ui.researchers import (
    create_researcher as _create_researcher,
)
from ci2lab.ui.researchers import (
    delete_researcher as _delete_researcher,
)
from ci2lab.ui.researchers import (
    get_researcher as _get_researcher,
)
from ci2lab.ui.researchers import (
    list_researchers as _list_researchers,
)
from ci2lab.ui.researchers import (
    update_researcher as _update_researcher,
)
from ci2lab.ui.server_parts.agent import (
    chat as _chat,
)
from ci2lab.ui.server_parts.agent import (
    chat_cancel as _chat_cancel,
)
from ci2lab.ui.server_parts.agent import (
    chat_start as _chat_start,
)
from ci2lab.ui.server_parts.agent import (
    save_completed_session as _save_completed_session,
)
from ci2lab.ui.server_parts.agent import (
    save_pending_session as _save_pending_session,
)
from ci2lab.ui.server_parts.api import (
    UI_ACTIONS,
)
from ci2lab.ui.server_parts.api import (
    delete_model as _delete_model,
)
from ci2lab.ui.server_parts.api import (
    delete_task_payload as _delete_task_payload,
)
from ci2lab.ui.server_parts.api import (
    finish_delete_task as _finish_delete_task,
)
from ci2lab.ui.server_parts.api import (
    finish_pull_task as _finish_pull_task,
)
from ci2lab.ui.server_parts.api import (
    health_payload as _health_payload,
)
from ci2lab.ui.server_parts.api import (
    models_payload as _models_payload,
)
from ci2lab.ui.server_parts.api import (
    pull_model as _pull_model,
)
from ci2lab.ui.server_parts.api import (
    pull_percent as _pull_percent,
)
from ci2lab.ui.server_parts.api import (
    pull_task_payload as _pull_task_payload,
)
from ci2lab.ui.server_parts.api import (
    recompute_pull_totals as _recompute_pull_totals,
)
from ci2lab.ui.server_parts.api import (
    record_pull_event as _record_pull_event,
)
from ci2lab.ui.server_parts.api import (
    run_delete_task as _run_delete_task,
)
from ci2lab.ui.server_parts.api import (
    run_pull_task as _run_pull_task,
)
from ci2lab.ui.server_parts.api import (
    system_payload as _system_payload,
)
from ci2lab.ui.server_parts.api import (
    tool_group as _tool_group,
)
from ci2lab.ui.server_parts.api import (
    tool_web_status as _tool_web_status,
)
from ci2lab.ui.server_parts.api import (
    tools_payload as _tools_payload,
)
from ci2lab.ui.server_parts.api import (
    update_delete_task as _update_delete_task,
)
from ci2lab.ui.server_parts.http import (
    UIState,
    run_ui,
)
from ci2lab.ui.server_parts.http import (
    content_type_for as _content_type,
)
from ci2lab.ui.server_parts.http import (
    handler_factory as _handler_factory,
)
from ci2lab.ui.server_parts.serializers import (
    bytes_to_gb as _bytes_to_gb,
)
from ci2lab.ui.server_parts.serializers import (
    delete_session_payload as _delete_session_payload,
)
from ci2lab.ui.server_parts.serializers import (
    disk_payload as _disk_payload,
)
from ci2lab.ui.server_parts.serializers import (
    format_upload_size as _format_upload_size,
)
from ci2lab.ui.server_parts.serializers import (
    list_runs as _list_runs,
)
from ci2lab.ui.server_parts.serializers import (
    message_text as _message_text,
)
from ci2lab.ui.server_parts.serializers import (
    public_delete_task as _public_delete_task,
)
from ci2lab.ui.server_parts.serializers import (
    public_pull_task as _public_pull_task,
)
from ci2lab.ui.server_parts.serializers import (
    safe_int as _safe_int,
)
from ci2lab.ui.server_parts.serializers import (
    session_payload as _session_payload,
)
from ci2lab.ui.server_parts.serializers import (
    session_title as _session_title,
)
from ci2lab.ui.server_parts.serializers import (
    sessions_payload as _sessions_payload,
)
from ci2lab.ui.server_parts.uploads import (
    DOCUMENT_UPLOAD_SUFFIXES,
    MAX_UPLOAD_BYTES,
    SUPPORTED_UPLOAD_SUFFIXES,
    UPLOAD_DIR_NAME,
)
from ci2lab.ui.server_parts.uploads import (
    extract_rubric_pdf as _extract_rubric_pdf,
)
from ci2lab.ui.server_parts.uploads import (
    is_upload_path as _is_upload_path,
)
from ci2lab.ui.server_parts.uploads import (
    normalize_attachments as _normalize_attachments,
)
from ci2lab.ui.server_parts.uploads import (
    prompt_with_uploaded_files as _prompt_with_uploaded_files,
)
from ci2lab.ui.server_parts.uploads import (
    safe_upload_name as _safe_upload_name,
)
from ci2lab.ui.server_parts.uploads import (
    unique_upload_path as _unique_upload_path,
)
from ci2lab.ui.server_parts.uploads import (
    upload_file as _upload_file,
)

__all__ = [
    "DOCUMENT_UPLOAD_SUFFIXES",
    "MAX_UPLOAD_BYTES",
    "SUPPORTED_UPLOAD_SUFFIXES",
    "UI_ACTIONS",
    "UPLOAD_DIR_NAME",
    "UIState",
    "run_ui",
]
