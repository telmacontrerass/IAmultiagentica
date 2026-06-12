"""
Bucle ReAct del arnés agéntico.

Flujo por ronda:
  1. Recortar historial al contexto del modelo
  2. Llamar al LLM (streaming opcional)
  3. Detectar tool calls (native, XML o fenced)
  4. Ejecutar herramientas → añadir resultados
  5. Repetir hasta respuesta sin tools o max_rounds
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.live import Live
from rich.text import Text

from ci2lab.contracts.types import HardwareProfile, ModelSelection
from ci2lab.harness.compact import manage_context
from ci2lab.harness.context import trim_messages
from ci2lab.harness.document_answer import maybe_answer_document_request
from ci2lab.harness.edit_followup import EditSignature, process_edit_round
from ci2lab.harness.llm_client import LLMClient, LLMResponse, StreamToken
from ci2lab.harness.llm_errors import LLMError, classify_request_error
from ci2lab.harness.messages import append_assistant_turn, append_tool_results
from ci2lab.harness.parsing import (
    looks_like_unparsed_tool_attempt,
    resolve_tool_calls,
    strip_tool_markup,
)
from ci2lab.harness.prompts import build_system_prompt
from ci2lab.harness.run_logger import RunLogger
from ci2lab.harness.session import save_session
from ci2lab.harness.policy import (
    POLICY_NUDGE_MESSAGE,
    POLICY_REPEAT_MESSAGE,
    is_policy_error,
    tool_call_signature,
)
from ci2lab.harness.mcp.session import close_mcp_manager
from ci2lab.harness.tools.registry import execute_tool, get_function_schemas
from ci2lab.harness.types import AgentConfig, ToolCall, ToolResult

console = Console()


def run_agent(
    user_prompt: str,
    selection: ModelSelection,
    *,
    hardware: HardwareProfile | None = None,  # noqa: ARG001
    config: AgentConfig | None = None,
    messages: list[dict[str, Any]] | None = None,
    on_round: Callable[[int, str], None] | None = None,
) -> str:
    """
    Ejecuta el bucle agéntico y devuelve la respuesta final.

    Si `messages` se pasa (sesión reanudada), se continúa el historial y se
    añade `user_prompt` como nuevo mensaje de usuario.
    """
    cfg = config or AgentConfig(cwd=".")
    client = LLMClient(selection)
    system = build_system_prompt(selection, cfg.cwd)

    if messages is None:
        history: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
    else:
        history = list(messages)
        if not any(m.get("role") == "system" for m in history):
            history.insert(0, {"role": "system", "content": system})
        history.append({"role": "user", "content": user_prompt})

    recent_sigs: deque[str] = deque(maxlen=6)
    policy_blocked_sigs: set[str] = set()
    policy_nudge_sent = False
    stuck_rounds = 0
    unparsed_tool_nudges = 0
    summary_failures = 0
    document_tool_nudges = 0
    document_tool_used = False
    completed_edits: set[EditSignature] = set()
    final_text = ""
    content = ""
    status = "success"
    log_error: str | None = None
    rounds_completed = 0
    hit_max_rounds = False

    run_log = RunLogger.maybe_create(cfg, selection, user_prompt)
    if run_log:
        run_log.start()

    try:
        for round_num in range(1, cfg.max_rounds + 1):
            console.print(f"[dim]── Ronda {round_num} ──[/dim]")
            rounds_completed = round_num
            if run_log:
                run_log.set_rounds_completed(round_num)

            history, summary_failures, compact_events = manage_context(
                history,
                client,
                selection.context_length,
                summary_failures=summary_failures,
            )
            for event in compact_events:
                console.print(f"[dim]{event}[/dim]")

            content = ""
            calls: list[ToolCall] = []
            initial_document_call = (
                _forced_document_read_tool_call(user_prompt, cfg.cwd)
                if not document_tool_used and round_num == 1
                else None
            )
            if initial_document_call:
                console.print(
                    "[yellow]Petición documental detectada; leyendo el documento "
                    "con read_document.[/yellow]"
                )
                calls = [initial_document_call]
            else:
                missing_document_message = (
                    _document_request_missing_message(
                        user_prompt,
                        cfg.cwd,
                        document_tool_used=document_tool_used,
                    )
                    if not document_tool_used and round_num == 1
                    else None
                )
                if missing_document_message:
                    final_text = missing_document_message
                    console.print(final_text)
                    append_assistant_turn(history, final_text)
                    _maybe_save(cfg, history, selection)
                    break

                trimmed = trim_messages(history, selection.context_length)
                tools = get_function_schemas(cfg) if selection.supports_tools else None

                try:
                    llm_response = _call_llm(client, trimmed, tools=tools, stream=cfg.stream)
                except LLMError as exc:
                    status = "llm_error"
                    log_error = exc.user_message
                    _maybe_save(cfg, history, selection)
                    raise
                except Exception as exc:  # noqa: BLE001
                    err = classify_request_error(
                        exc, model=selection.ollama_tag, url=client.chat_url
                    )
                    console.print(f"[red]{err.user_message}[/red]")
                    status = "llm_error"
                    log_error = err.user_message
                    _maybe_save(cfg, history, selection)
                    raise err from exc

                content = llm_response.content or ""
                if on_round:
                    on_round(round_num, content)

                calls = resolve_tool_calls(
                    content,
                    llm_response.tool_calls,
                    tool_mode=selection.tool_mode,
                )
                calls = _prepend_missing_reads(calls, user_prompt)
            forced_document_call = (
                _forced_document_read_tool_call(user_prompt, cfg.cwd)
                if not calls and not document_tool_used and document_tool_nudges >= 1
                else None
            )
            if forced_document_call:
                console.print(
                    "[yellow]El modelo siguió sin usar herramientas; ejecutando "
                    "read_document automáticamente para el documento mencionado.[/yellow]"
                )
                calls = [forced_document_call]

            if not calls:
                document_hint = _document_tool_retry_hint(
                    user_prompt,
                    selection_tool_mode=selection.tool_mode,
                    cwd=cfg.cwd,
                )
                if (
                    document_hint
                    and not document_tool_used
                    and document_tool_nudges < 1
                    and selection.supports_tools
                ):
                    document_tool_nudges += 1
                    console.print(
                        "[yellow]La petición menciona un documento pero el modelo no usó "
                        "herramientas; reintentando con read_document/grep.[/yellow]"
                    )
                    append_assistant_turn(history, content)
                    history.append({"role": "user", "content": document_hint})
                    _maybe_save(cfg, history, selection)
                    continue

                missing_document_message = _document_request_missing_message(
                    user_prompt,
                    cfg.cwd,
                    document_tool_used=document_tool_used,
                )
                if missing_document_message:
                    final_text = missing_document_message
                    console.print(final_text)
                    append_assistant_turn(history, final_text)
                    _maybe_save(cfg, history, selection)
                    break

                if (
                    looks_like_unparsed_tool_attempt(content)
                    and unparsed_tool_nudges < 2
                    and selection.supports_tools
                ):
                    unparsed_tool_nudges += 1
                    console.print(
                        "[yellow]Tool call detected as text but not executed; "
                        "asking the model to retry.[/yellow]"
                    )
                    append_assistant_turn(history, content)
                    if selection.tool_mode == "fenced":
                        hint = (
                            "Your previous tool call was not executed. "
                            "Use a fenced block with the tool name as the tag, e.g.\n"
                            "```read_file\n"
                            "Pruebas.py\n"
                            "```\n"
                            "or\n"
                            "```edit_file\n"
                            '{"path": "Pruebas.py", "old_string": "...", "new_string": "..."}\n'
                            "```\n"
                            "Never run read_file or edit_file as shell commands (`bash read_file ...`). "
                            "Do not reply with plain JSON only."
                        )
                    else:
                        hint = (
                            "Your previous tool call was not executed. "
                            "Invoke the tool through function calling, or use a "
                            "```write_file fenced block with JSON arguments."
                        )
                    history.append({"role": "user", "content": hint})
                    _maybe_save(cfg, history, selection)
                    continue

                final_text = strip_tool_markup(content).strip() or content.strip()
                if final_text and not cfg.stream:
                    console.print(final_text)
                elif final_text and cfg.stream:
                    console.print()  # newline tras streaming
                append_assistant_turn(history, final_text or content)
                _maybe_save(cfg, history, selection)
                break

            sig = "|".join(
                f"{c.name}:{hashlib.md5(str(c.arguments).encode()).hexdigest()[:8]}"
                for c in calls
            )
            if any(_is_document_read_tool_call(c.name, c.arguments) for c in calls):
                document_tool_used = True
            if sig in recent_sigs:
                stuck_rounds += 1
            else:
                stuck_rounds = 0
            recent_sigs.append(sig)

            if stuck_rounds >= 2:
                console.print("[yellow]Bucle detectado; pidiendo respuesta final.[/yellow]")
                history.append({
                    "role": "user",
                    "content": (
                        "Deja de repetir la misma herramienta. "
                        "Responde al usuario con lo que ya sabes."
                    ),
                })
                continue

            append_assistant_turn(history, content, calls)
            results = []
            round_policy_error = False
            for call in calls:
                console.print(f"[cyan]▶ {call.name}[/cyan] {_summarize_args(call.arguments)}")
                started_at = datetime.now(timezone.utc)
                sig = tool_call_signature(call)
                if sig in policy_blocked_sigs:
                    result = ToolResult(
                        tool_name=call.name,
                        content=POLICY_REPEAT_MESSAGE,
                        is_error=True,
                        call_id=call.call_id,
                        outcome="blocked_by_policy",
                    )
                else:
                    result = execute_tool(call, cfg)
                    if is_policy_error(result):
                        policy_blocked_sigs.add(sig)
                        round_policy_error = True
                ended_at = datetime.now(timezone.utc)
                if run_log:
                    run_log.record_tool_call(
                        round_num=round_num,
                        call=call,
                        result=result,
                        started_at=started_at,
                        ended_at=ended_at,
                    )
                if result.is_error:
                    console.print(f"[red]  ✗ {result.content[:200]}[/red]")
                else:
                    preview = result.content[:120].replace("\n", " ")
                    console.print(f"[green]  ✓[/green] {preview}...")
                results.append(result)

            append_tool_results(history, results)
            document_answer = _document_direct_answer(results, user_prompt)
            if document_answer:
                final_text = document_answer
                console.print(final_text)
                append_assistant_turn(history, final_text)
                _maybe_save(cfg, history, selection)
                break
            document_followup = _document_tool_result_followup(results, user_prompt)
            if document_followup:
                history.append({"role": "user", "content": document_followup})
            edit_followup = process_edit_round(
                calls,
                results,
                cwd=cfg.cwd,
                user_prompt=user_prompt,
                completed_edits=completed_edits,
            )
            if edit_followup:
                history.append({"role": "user", "content": edit_followup})
            if round_policy_error and not policy_nudge_sent:
                history.append({"role": "user", "content": POLICY_NUDGE_MESSAGE})
                policy_nudge_sent = True
            _maybe_save(cfg, history, selection)
        else:
            hit_max_rounds = True
            status = "max_rounds"
            final_text = (
                strip_tool_markup(content).strip()
                if content
                else "Se alcanzó el límite de rondas sin respuesta final."
            )
            _maybe_save(cfg, history, selection)

        return final_text
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    finally:
        close_mcp_manager(cfg.cwd)
        if run_log:
            finalize_error = log_error
            if status == "max_rounds" and not finalize_error:
                finalize_error = final_text or "Se alcanzó el límite de rondas sin respuesta final."
            run_log.finalize(
                status=status,
                final_answer=final_text,
                conversation=history,
                error=finalize_error,
            )


def _call_llm(
    client: LLMClient,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    stream: bool,
) -> LLMResponse:
    if not stream:
        return client.chat(messages, tools=tools)

    llm_response: LLMResponse | None = None
    buffer = Text()

    with Live(buffer, console=console, refresh_per_second=12, transient=False) as live:
        for event in client.stream_chat(messages, tools=tools):
            if isinstance(event, StreamToken):
                buffer.append(event.text)
                live.update(buffer)
            else:
                llm_response = event

    if llm_response is None:
        return LLMResponse(content=buffer.plain, tool_calls=[], raw={})
    if not llm_response.content and buffer.plain:
        llm_response = LLMResponse(
            content=buffer.plain,
            tool_calls=llm_response.tool_calls,
            raw=llm_response.raw,
        )
    return llm_response


def _maybe_save(
    cfg: AgentConfig,
    messages: list[dict[str, Any]],
    selection: ModelSelection,
) -> None:
    if not cfg.session_id:
        return
    path = save_session(
        cfg.session_id,
        messages=messages,
        model_tag=selection.ollama_tag,
        cwd=cfg.cwd,
    )
    console.print(f"[dim]Sesión guardada: {path}[/dim]")


def _prepend_missing_reads(calls: list[ToolCall], user_prompt: str) -> list[ToolCall]:
    """Si el usuario pidió leer un archivo y el modelo solo llama edit_file, leer primero."""
    if not calls or not re.search(r"\bread\b", user_prompt, re.IGNORECASE):
        return calls
    edit_paths = {
        str(call.arguments["path"])
        for call in calls
        if call.name == "edit_file" and call.arguments.get("path")
    }
    if not edit_paths:
        return calls
    read_paths = {
        str(call.arguments["path"])
        for call in calls
        if call.name in ("read_file", "read_document") and call.arguments.get("path")
    }
    missing = sorted(edit_paths - read_paths)
    if not missing:
        return calls
    prefixed = [
        ToolCall(
            name="read_file",
            arguments={"path": path},
            call_id=f"call_{uuid.uuid4().hex[:8]}",
        )
        for path in missing
    ]
    return prefixed + calls


def _summarize_args(args: dict) -> str:
    if "command" in args:
        cmd = args["command"]
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if "url" in args:
        url = str(args["url"])
        return url[:60] + ("..." if len(url) > 60 else "")
    if "question" in args:
        q = str(args["question"])
        return q[:60] + ("..." if len(q) > 60 else "")
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    if "todos" in args and isinstance(args["todos"], list):
        return f"{len(args['todos'])} items"
    return ""


_DOCUMENT_EXTENSIONS = (
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "csv",
    "tsv",
    "md",
    "rst",
    "txt",
    "text",
    "json",
    "yaml",
    "yml",
)
_DOCUMENT_PATH_RE = re.compile(
    rf"(?P<path>[^\s`\"']+\.({'|'.join(_DOCUMENT_EXTENSIONS)}))\b",
    re.IGNORECASE,
)


def _document_tool_retry_hint(
    user_prompt: str,
    *,
    selection_tool_mode: str,
    cwd: str,
) -> str | None:
    if not _looks_like_document_read_request(user_prompt):
        return None
    document_path = _document_path_from_prompt(user_prompt, cwd)
    if not document_path:
        return None

    if selection_tool_mode == "fenced":
        return (
            "La petición del usuario requiere leer un documento del directorio de trabajo. "
            "No digas que no puedes acceder al archivo: tienes herramientas locales. "
            "Llama ahora a la herramienta `read_document` con este bloque exacto, espera el "
            "resultado y después responde a la tarea del usuario:\n"
            "```read_document\n"
            f"{document_path}\n"
            "```"
        )

    return (
        "La petición del usuario requiere leer un documento del directorio de trabajo. "
        "No digas que no puedes acceder al archivo: tienes herramientas locales. "
        f"Invoca ahora la herramienta read_document con path={document_path!r}, espera el "
        "resultado y después responde a la tarea del usuario."
    )


def _is_document_read_tool_call(tool_name: str, args: dict[str, Any]) -> bool:
    if tool_name in {"read_file", "read_document"}:
        return _is_supported_document_path(str(args.get("path", "")))
    if tool_name == "grep":
        path = str(args.get("path", "")).lower()
        glob = str(args.get("glob", "")).lower()
        return _is_supported_document_path(path) or any(
            f".{ext}" in glob for ext in _DOCUMENT_EXTENSIONS
        )
    return False


def _forced_document_read_tool_call(user_prompt: str, cwd: str) -> ToolCall | None:
    if not _looks_like_document_read_request(user_prompt):
        return None
    document_path = _document_path_from_prompt(user_prompt, cwd)
    if not document_path:
        return None
    return ToolCall(
        name="read_document",
        arguments={"path": document_path},
        call_id="auto_document_read",
    )


def _document_tool_result_followup(
    results: list[ToolResult],
    original_user_prompt: str,
) -> str | None:
    document_outputs = [
        result.content
        for result in results
        if result.tool_name in {"read_file", "read_document"}
        and not result.is_error
        and ("Texto extraido:" in result.content or "[PDF page " in result.content)
    ]
    if not document_outputs:
        return None
    content = "\n\n".join(document_outputs)
    return (
        "Contenido del documento leido con la herramienta `read_document`:\n\n"
        f"{content}\n\n"
        "Ahora responde a la petición original usando exclusivamente ese contenido. "
        f"Petición original: {original_user_prompt}"
    )


def _document_direct_answer(
    results: list[ToolResult],
    original_user_prompt: str,
) -> str | None:
    document_outputs = [
        result.content
        for result in results
        if result.tool_name in {"read_file", "read_document"}
        and not result.is_error
        and ("Texto extraido:" in result.content or "[PDF page " in result.content)
    ]
    return maybe_answer_document_request(original_user_prompt, document_outputs)


def _is_supported_document_path(path: str) -> bool:
    low = path.lower()
    return any(low.endswith(f".{ext}") for ext in _DOCUMENT_EXTENSIONS)


_DOCUMENT_TYPE_EXTENSIONS = {
    "pdf": {".pdf"},
    "word": {".docx"},
    "docx": {".docx"},
    "excel": {".xlsx", ".csv", ".tsv"},
    "xlsx": {".xlsx"},
    "csv": {".csv"},
    "powerpoint": {".pptx"},
    "presentacion": {".pptx"},
    "presentación": {".pptx"},
    "pptx": {".pptx"},
}
_DOCUMENT_REQUEST_CUES = frozenset({
    "archivo",
    "documento",
    "fichero",
    "pdf",
    "word",
    "docx",
    "excel",
    "xlsx",
    "csv",
    "powerpoint",
    "presentacion",
    "presentación",
    "pptx",
})
_SKIPPED_DOCUMENT_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "runs",
})


def _document_path_from_prompt(user_prompt: str, cwd: str) -> str | None:
    match = _DOCUMENT_PATH_RE.search(user_prompt)
    if match:
        return match.group("path")

    candidates = _document_candidates(cwd, _requested_document_extensions(user_prompt))
    if not candidates:
        return None

    prompt_tokens = set(_word_tokens(user_prompt))
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        stem_tokens = set(_word_tokens(candidate.stem))
        score = len(prompt_tokens & stem_tokens)
        if candidate.stem.lower() in user_prompt.lower():
            score += 3
        if score:
            scored.append((score, _relative_document_path(candidate, cwd)))

    if scored:
        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1]

    requested_exts = _requested_document_extensions(user_prompt)
    if requested_exts and len(candidates) == 1:
        return _relative_document_path(candidates[0], cwd)
    return None


def _document_request_missing_message(
    user_prompt: str,
    cwd: str,
    *,
    document_tool_used: bool,
) -> str | None:
    if document_tool_used or not _looks_like_document_read_request(user_prompt):
        return None
    if _document_path_from_prompt(user_prompt, cwd):
        return None

    candidates = _document_candidates(cwd, _requested_document_extensions(user_prompt))
    if not candidates:
        return (
            "No encuentro un documento claro para leer. Escribe el nombre del archivo "
            "con extension, por ejemplo: `resume prueba.pdf`."
        )
    shown = [
        f"- {_relative_document_path(candidate, cwd)}"
        for candidate in candidates[:8]
    ]
    more = "" if len(candidates) <= 8 else f"\n... y {len(candidates) - 8} mas"
    return (
        "No sé con seguridad qué documento quieres leer. Prueba con uno de estos:\n\n"
        + "\n".join(shown)
        + more
    )


def _requested_document_extensions(user_prompt: str) -> set[str] | None:
    text = user_prompt.lower()
    requested: set[str] = set()
    for marker, extensions in _DOCUMENT_TYPE_EXTENSIONS.items():
        if marker in text:
            requested.update(extensions)
    return requested or None


def _document_candidates(cwd: str, extensions: set[str] | None = None) -> list[Path]:
    root = Path(cwd).resolve()
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _SKIPPED_DOCUMENT_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {f".{ext}" for ext in _DOCUMENT_EXTENSIONS}:
            continue
        if extensions and suffix not in extensions:
            continue
        candidates.append(path)
        if len(candidates) >= 100:
            break
    return sorted(candidates, key=lambda item: (len(item.parts), item.name.lower()))


def _relative_document_path(path: Path, cwd: str) -> str:
    try:
        return path.relative_to(Path(cwd).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _word_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower())
        if len(token) >= 3
    ]


def _looks_like_document_read_request(user_prompt: str) -> bool:
    text = user_prompt.lower()
    write_verbs = (
        "crea",
        "crear",
        "guarda",
        "guardar",
        "escribe",
        "escribir",
        "edita",
        "editar",
        "modifica",
        "modificar",
        "sobrescribe",
        "sobrescribir",
    )
    if any(verb in text for verb in write_verbs):
        return False
    read_verbs = (
        "abre",
        "abrir",
        "analiza",
        "analizar",
        "busca",
        "buscar",
        "consulta",
        "consultar",
        "corrige",
        "corregir",
        "extrae",
        "extraer",
        "lee",
        "leer",
        "resume",
        "resumir",
        "revisa",
        "revisar",
    )
    has_read_intent = any(verb in text for verb in read_verbs)
    has_document_reference = (
        bool(_DOCUMENT_PATH_RE.search(user_prompt))
        or any(cue in text for cue in _DOCUMENT_REQUEST_CUES)
    )
    return has_read_intent and has_document_reference
