"""Interactive REPL mode for the harness."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.panel import Panel

if TYPE_CHECKING:
    from rich.status import Status

    from ci2lab.harness.multiagent.paper_review import ReviewContext

from ci2lab.console import active_progress, console
from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.llm_errors import LLMError
from ci2lab.harness.multiagent import run_multi_agent
from ci2lab.harness.query.loop import run_agent
from ci2lab.harness.session import (
    delete_session,
    is_delete_session_request,
    list_sessions,
    load_session,
    new_session_id,
    save_session,
)
from ci2lab.harness.skills.loader import load_skills
from ci2lab.harness.terminal_input import read_prompt_line
from ci2lab.harness.tools.filesystem_parts.documents import (
    pdf_has_extractable_text,
)
from ci2lab.harness.tools.skill_tool import invoke_skill_for_repl
from ci2lab.harness.types import AgentConfig
from ci2lab.harness.vision import (
    extract_image_paths,
    find_image_candidates,
    is_vision_model,
)
from ci2lab.harness.vision_exercise import (
    is_exercise_review_request,
    is_transcription_request,
    select_visual_skill,
)


class _TransientProgress:
    """Render one replaceable status line and remove it when work finishes."""

    def __init__(self) -> None:
        """Initialise the progress holder with no active status line."""
        self._status: Status | None = None

    def update(self, label: str) -> None:
        """Show or update the status line with *label*; clear it if empty."""
        if not label:
            self.clear()
            return
        rendered = f"[dim italic cyan]{label}[/dim italic cyan]"
        if self._status is None:
            self._status = console.status(rendered, spinner="dots")
            self._status.start()
            # Let interactive prompts (e.g. permission requests) pause the
            # spinner while they read input, otherwise it hides the prompt.
            active_progress.set(self._status)
        else:
            self._status.update(rendered)

    def clear(self) -> None:
        """Stop and remove the active status line if one is showing."""
        if self._status is not None:
            active_progress.clear(self._status)
            self._status.stop()
            self._status = None


def _extract_inline_images(
    line: str,
    config: AgentConfig,
    selection: ModelSelection,
) -> tuple[str, list[str]]:
    """Detect image paths in *line*, print feedback, return (prompt, paths).

    If images are found but the active model cannot handle them and no
    fallback vision_model is configured, a warning is printed and the
    paths are returned empty so they are not silently dropped without notice.

    When an image-like name is mentioned but the file does not exist, a
    "not found — did you mean?" warning is printed immediately so the user
    can correct the typo before the bad turn pollutes the session history.

    Args:
        line: The raw user input line that may contain image file paths.
        config: Active agent configuration (provides ``cwd`` and vision flags).
        selection: The active model selection used to check vision capability.

    Returns:
        A ``(prompt, paths)`` tuple where ``prompt`` is the user text with image
        paths stripped and any context notes prepended, and ``paths`` is the list
        of resolved image paths to attach (empty if none are usable).
    """
    import difflib
    from pathlib import Path

    cleaned, paths = extract_image_paths(line, config.cwd)

    # Warn about any image-like strings that were mentioned but don't exist.
    # Also build a context note injected into the prompt so the model knows
    # immediately — preventing it from spending rounds trying to read the file.
    candidates = find_image_candidates(line)
    resolved_names = {Path(p).name.lower() for p in paths}
    not_found_notes: list[str] = []

    try:
        workspace_images = [
            f.name
            for f in Path(config.cwd).iterdir()
            if f.is_file()
            and f.suffix.lower()
            in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".pdf"}
        ]
    except OSError:
        workspace_images = []

    for candidate in candidates:
        name = Path(candidate).name
        if name.lower() in resolved_names:
            continue

        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            candidate_path = Path(config.cwd) / candidate

        if (
            candidate_path.is_file()
            and candidate_path.suffix.lower() == ".pdf"
            and pdf_has_extractable_text(candidate_path)
        ):
            console.print(
                f"[dim]PDF detected: {name} — text document (use read_document, not vision)[/dim]"
            )
            not_found_notes.append(
                f"[Context: '{name}' is a text-based PDF. Use read_document to "
                f"extract its content — do NOT treat it as an image.]"
            )
            continue

        suggestions = difflib.get_close_matches(name, workspace_images, n=2, cutoff=0.55)
        if suggestions:
            hint = "  Did you mean: " + ", ".join(f"[bold]{s}[/bold]" for s in suggestions)
            console.print(f"[yellow]'{name}' not found in workspace.[/yellow]{hint}")
            note = (
                f"[Context: '{name}' was mentioned as an image but does not exist "
                f"in the workspace. Similar files: {', '.join(suggestions)}. "
                f"Tell the user the file was not found and suggest the correct name. "
                f"Do NOT use read_file or file tools to search for it.]"
            )
        else:
            console.print(
                f"[yellow]'{name}' not found in workspace — image will not be attached.[/yellow]"
            )
            note = (
                f"[Context: '{name}' was mentioned as an image but does not exist "
                f"in the workspace. Tell the user the file was not found. "
                f"Do NOT use read_file or file tools to search for it.]"
            )
        not_found_notes.append(note)

    if not paths:
        # Prepend not-found notes so the model answers directly without looping.
        if not_found_notes:
            enriched = "\n".join(not_found_notes) + "\n\n" + line
            return enriched, []
        return line, []

    pdf_context_notes: list[str] = []
    for p in paths:
        name = Path(p).name
        if Path(p).suffix.lower() == ".pdf":
            # Show page count so the user knows how many pages will be processed.
            try:
                import fitz

                _doc = fitz.open(p)
                _n = len(_doc)
                _doc.close()
                _shown: int | str = min(_n, 10)
                _suffix = f" ({_shown} of {_n} pages)" if _n > 1 else " (1 page)"
            except Exception:
                _shown = "?"
                _suffix = ""
            console.print(f"[dim]PDF detected: {name}{_suffix} — will render pages as images[/dim]")
            console.print(
                "[dim]Vision PDF requests can take several minutes on first run — please wait.[/dim]"
            )
            # Tell the model the pages are already visually attached so it does
            # not waste tool calls trying to read_document the file.
            pdf_context_notes.append(
                f"[Context: '{name}' has been rendered as page images and attached "
                f"to this message. Do NOT call read_document or any file tool on "
                f"'{name}' — the content is already visible in the attached images "
                f"or in the vision-model transcription injected below. "
                f"The harness loads a visual-document skill automatically: a "
                f"transcription skill when you ask to transcribe/read it, or the "
                f"review skill when you ask to check or audit calculations. Follow "
                f"whichever skill is injected.]"
            )
        else:
            console.print(f"[dim]Image detected: {name}[/dim]")

    # Prepend PDF context notes so the model sees them before its tool schemas.
    if pdf_context_notes:
        cleaned = "\n".join(pdf_context_notes) + "\n\n" + (cleaned or line)

    if not config.vision_enabled:
        console.print(
            "[yellow]Vision is disabled — images ignored.[/yellow] "
            "[dim]Set vision_enabled: true in ~/.ci2lab/settings.json[/dim]"
        )
        return cleaned, []

    if not is_vision_model(selection.ollama_tag) and not (config.vision_model or "").strip():
        console.print(
            "[yellow]Image detected but the active model is not vision-capable "
            "and no fallback vision_model is configured — image ignored.[/yellow]\n"
            "[dim]Tip: restart with a vision model "
            "(e.g. ci2lab --model qwen2.5vl:7b chat) "
            'or add  vision_model: "llava"  to ~/.ci2lab/settings.json[/dim]'
        )
        return cleaned, []

    return cleaned, paths


def run_repl(
    selection: ModelSelection,
    config: AgentConfig,
    *,
    session_id: str | None = None,
    multi_agent: bool = False,
    review_context: ReviewContext | None = None,
) -> None:
    """Run the interactive REPL loop until the user exits.

    Reads prompts in a loop, dispatching slash commands (``/save``, ``/resume``,
    ``/skills``, etc.), detecting inline image attachments, and forwarding each
    turn to either the classic single-agent runner or the multi-agent
    orchestrator. Session history is persisted as turns complete.

    Args:
        selection: The model selection driving the run (tag, tool mode, etc.).
        config: Active agent configuration, mutated in place with the session id
            and per-turn image attachments.
        session_id: Optional id of an existing session to resume; a new id is
            generated when omitted.
        multi_agent: When ``True``, route turns through the multi-agent
            orchestrator instead of the classic single-agent loop.
        review_context: Addressable manuscript index and reviewer metadata for
            an explicitly grounded scientific peer-review project.

    Returns:
        None. The function returns when the user exits or an unresumable session
        is requested.
    """
    sid = session_id or new_session_id()
    config.session_id = sid

    history = None
    last_user_prompt: str | None = None
    last_error_message: str | None = None
    session_vision_paths: list[str] = []
    if session_id:
        data = load_session(session_id)
        if data:
            stored_project_id = str(data.get("project_id") or "")
            active_project_id = str(config.project_id or "")
            if stored_project_id != active_project_id:
                console.print(
                    "[red]This session belongs to a different project and cannot "
                    "be resumed here.[/red]"
                )
                return
            history = data.get("messages")
            console.print(f"[dim]Resuming session {session_id}[/dim]")

    project_line = ""
    if config.project_id:
        from ci2lab.ui.projects import get_project

        project = get_project(config.project_id)
        if project:
            project_line = (
                f"Project: {project['name']} ({project['source_count']} persistent sources)\n"
            )

    console.print(
        Panel(
            f"[bold]ci2lab REPL[/bold]\n"
            f"{project_line}"
            f"Model: {selection.ollama_tag}\n"
            f"Tool mode: {selection.tool_mode}\n"
            f"Mode: {'multi-agent' if multi_agent else 'classic'}\n"
            f"CWD: {config.cwd}\n"
            f"Session: {sid}\n\n"
            "Type your request. [bold]Ctrl+V[/bold] pastes; [bold]Enter[/bold] sends; "
            "[bold]Alt+Enter[/bold] new line.\n"
            "Commands: [bold]/exit[/bold], [bold]/save[/bold], [bold]/clear[/bold], "
            "[bold]/delete[/bold], [bold]/sessions[/bold], [bold]/resume ID[/bold], "
            "[bold]/retry[/bold], [bold]/why[/bold], "
            "[bold]/skills[/bold], [bold]/skill-name[/bold]",
            title="Local agent",
            border_style="blue",
        )
    )

    while True:
        try:
            line = read_prompt_line("You> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]See you later.[/dim]")
            break

        if not line:
            continue
        if line.lower() in {"/exit", "/quit", "exit", "quit"}:
            break
        if line.lower() == "/sessions":
            rows = list_sessions()
            if not rows:
                console.print("[dim]No saved sessions.[/dim]")
            else:
                for row in rows[:20]:
                    console.print(
                        f"- [bold]{row.get('title') or 'Conversation'}[/bold] "
                        f"[dim]({row['id']})[/dim] · {row['model']} · "
                        f"{row['updated_at'][:19]} · {row['cwd']}"
                    )
            continue
        if line.lower().startswith("/resume "):
            target = line.split(maxsplit=1)[1].strip()
            if not target:
                console.print("[yellow]Usage: /resume <session_id>[/yellow]")
                continue
            data = load_session(target)
            if not data:
                console.print(f"[yellow]Session {target} does not exist.[/yellow]")
                continue
            if str(data.get("project_id") or "") != str(config.project_id or ""):
                console.print(
                    "[yellow]That session belongs to a different project and "
                    "cannot be resumed here.[/yellow]"
                )
                continue
            sid = target
            config.session_id = sid
            history = data.get("messages")
            console.print(f"[green]Session {sid} loaded.[/green]")
            continue
        if line.lower() == "/retry":
            if not last_user_prompt:
                console.print("[yellow]No previous request to retry.[/yellow]")
                continue
            line = last_user_prompt
            console.print(f"[dim]Retrying: {line}[/dim]")
        if line.lower() == "/why":
            if not last_error_message:
                console.print("[dim]No recent failure recorded.[/dim]")
            else:
                console.print(
                    "[yellow]Last error:[/yellow]\n"
                    f"{last_error_message}\n\n"
                    "[dim]Next step: fix the problem and use /retry "
                    "or run `ci2lab doctor`.[/dim]"
                )
            continue
        if line.lower() == "/clear":
            history = (
                [{"role": "system", "content": history[0]["content"]}]
                if history and history[0].get("role") == "system"
                else None
            )
            session_vision_paths = []
            console.print("[dim]History cleared (system kept).[/dim]")
            continue
        if line.lower() == "/save":
            if history:
                path = save_session(
                    sid,
                    messages=history,
                    model_tag=selection.ollama_tag,
                    cwd=config.cwd,
                    token_usage=config.token_usage.to_dict(),
                    project_id=config.project_id,
                )
                console.print(f"[green]Saved to {path}[/green]")
            else:
                console.print("[yellow]Nothing to save yet.[/yellow]")
            continue
        if is_delete_session_request(line):
            deleted = delete_session(sid)
            history = None
            if deleted:
                console.print(f"[green]Session {sid} deleted.[/green]")
            else:
                console.print("[yellow]There was no saved session to delete.[/yellow]")
            continue
        if line.lower() == "/skills":
            skills = load_skills(config.cwd)
            if not skills:
                console.print("[dim]No skills found in .ci2lab/skills/ or ~/.ci2lab/skills/[/dim]")
            else:
                for name in sorted(skills):
                    skill = skills[name]
                    src = skill.source
                    console.print(f"- [bold]{name}[/bold] ({src}): {skill.description}")
            continue
        if line.startswith("/"):
            skill_line = line[1:].strip()
            if skill_line and not skill_line.lower().startswith(
                ("exit", "quit", "save", "clear", "delete", "forget")
            ):
                parts = skill_line.split(maxsplit=1)
                skill_name = parts[0]
                skill_args = parts[1] if len(parts) > 1 else ""
                skills = load_skills(config.cwd)
                if skill_name in skills:
                    config.skill_allowed_tools = None
                    body = invoke_skill_for_repl(config, skill_name, skill_args)
                    user_request = skill_args.strip()
                    if (
                        user_request.startswith("http://") or user_request.startswith("https://")
                    ) and " " not in user_request:
                        user_request = f"URL: {user_request}"
                    prompt = (
                        f"{body}\n\n---\nUser request: "
                        f"{user_request or '(use skill instructions above)'}"
                    )
                    execution_prompt = _project_prompt(config, prompt)
                    progress = _TransientProgress()
                    try:
                        last_user_prompt = line
                        if multi_agent:
                            final_text = run_multi_agent(
                                execution_prompt,
                                selection,
                                config=config,
                                on_progress=progress.update,
                                review_context=review_context,
                            )
                            if final_text:
                                console.print(final_text)
                                history = (history or []) + [
                                    {"role": "user", "content": prompt},
                                    {"role": "assistant", "content": final_text},
                                ]
                                save_session(
                                    sid,
                                    messages=history,
                                    model_tag=selection.ollama_tag,
                                    cwd=config.cwd,
                                    token_usage=config.token_usage.to_dict(),
                                    project_id=config.project_id,
                                )
                        else:
                            final_text = run_agent(
                                execution_prompt,
                                selection,
                                config=config,
                                messages=history,
                                on_progress=progress.update,
                            )
                            if config.project_id:
                                history = (history or []) + [
                                    {"role": "user", "content": prompt},
                                    {"role": "assistant", "content": final_text},
                                ]
                                save_session(
                                    sid,
                                    messages=history,
                                    model_tag=selection.ollama_tag,
                                    cwd=config.cwd,
                                    token_usage=config.token_usage.to_dict(),
                                    project_id=config.project_id,
                                )
                        last_error_message = None
                    except LLMError as exc:
                        console.print(f"[red]{exc.user_message}[/red]")
                        last_error_message = exc.user_message
                        continue
                    finally:
                        progress.clear()
                    data = load_session(sid)
                    if data:
                        history = data.get("messages")
                    continue

        # Scan the user's message for image file paths typed inline.
        # Paths are stripped from the text and attached as vision content,
        # matching the behaviour of Ollama's own REPL but working for both
        # absolute paths and bare filenames relative to the workspace.
        prompt, detected_images = _extract_inline_images(line, config, selection)

        _visual_skill = select_visual_skill(line) if detected_images else None
        if _visual_skill is not None:
            console.print(f"[dim]Will apply skill: {_visual_skill}[/dim]")

        # Re-attach the last PDF/images on follow-up turns so the model re-reads
        # the pages instead of relying on its earlier (possibly wrong) summary.
        if detected_images:
            session_vision_paths = list(detected_images)
        elif session_vision_paths:
            detected_images = list(session_vision_paths)
            names = ", ".join(Path(p).name for p in detected_images)
            console.print(f"[dim]Re-attaching: {names}[/dim]")
            follow_note = (
                "[Context: The document pages are re-attached to this message. "
                "Re-read the transcription/images directly — do not rely on earlier "
                "summaries. Follow the review_handwritten_exercise skill format: "
                "audit with impact classification and provide a corrected solution "
                "when errors affect the final answer.]"
            )
            prompt = follow_note + "\n\n" + prompt

        execution_prompt = _project_prompt(config, prompt)

        progress = _TransientProgress()
        try:
            config.skill_allowed_tools = None
            last_user_prompt = line
            # Temporarily attach images for this turn (new or re-attached).
            _prior_images = config.image_paths
            if detected_images:
                config.image_paths = detected_images

            if multi_agent:
                final_text = run_multi_agent(
                    execution_prompt,
                    selection,
                    config=config,
                    on_progress=progress.update,
                    review_context=review_context,
                )
                if final_text:
                    console.print(final_text)
                    history = (history or []) + [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": final_text},
                    ]
                    save_session(
                        sid,
                        messages=history,
                        model_tag=selection.ollama_tag,
                        cwd=config.cwd,
                        token_usage=config.token_usage.to_dict(),
                        project_id=config.project_id,
                    )
            elif history is None:
                final_text = run_agent(
                    execution_prompt,
                    selection,
                    config=config,
                    on_progress=progress.update,
                )
            else:
                final_text = run_agent(
                    execution_prompt,
                    selection,
                    config=config,
                    messages=history,
                    on_progress=progress.update,
                )
            if config.project_id and not multi_agent:
                history = (history or []) + [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": final_text},
                ]
                save_session(
                    sid,
                    messages=history,
                    model_tag=selection.ollama_tag,
                    cwd=config.cwd,
                    token_usage=config.token_usage.to_dict(),
                    project_id=config.project_id,
                )
            last_error_message = None
            if (
                final_text
                and config.project_id
                and config.multiagent_flow == "paper_review"
                and "PAPER REVIEW NOT POSSIBLE" not in final_text
            ):
                _export_project_paper_review(final_text, config.project_id)
            # Deterministically save the model's answer to a .md file so the
            # transcription (or audit/math) survives outside the terminal.
            # Scoped to visual-document turns to avoid writing a file for every
            # chat message.
            if final_text and detected_images:
                if is_exercise_review_request(line):
                    _export_review_markdown(final_text, config.cwd, detected_images)
                elif is_transcription_request(line):
                    _export_transcription_markdown(final_text, config.cwd, detected_images)
        except LLMError as exc:
            console.print(f"[red]{exc.user_message}[/red]")
            last_error_message = exc.user_message
            continue
        finally:
            config.image_paths = _prior_images  # restore for next turn
            progress.clear()

        data = load_session(sid)
        if data:
            history = data.get("messages")


def _export_project_paper_review(final_text: str, project_id: str) -> None:
    """Persist a terminal paper-review result as a project Markdown artifact."""
    from datetime import UTC, datetime

    from ci2lab.ui.projects import save_project_artifact

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    result = save_project_artifact(
        project_id,
        f"paper-review-corrections-{stamp}.md",
        final_text.rstrip() + "\n",
    )
    artifact = result.get("artifact") if result.get("ok") else None
    if isinstance(artifact, dict):
        console.print(f"[green]Paper-review report saved:[/green] {artifact.get('name')}")
    elif not result.get("ok"):
        console.print(f"[yellow]Could not save paper-review report: {result.get('error')}[/yellow]")


def _latex_to_plaintext(text: str) -> str:
    """Best-effort conversion of model LaTeX to plain Unicode/ASCII.

    phi4 often emits LaTeX (``\\text{}``, ``\\frac{}``, ``\\(...\\)``,
    ``^\\circ``, ``\\,``) even when told not to; a plain Markdown viewer shows
    those as garbled fragments (``C8H18`` -> ``8{18}``, ``°C`` -> ``^``). This
    strips the common commands deterministically so the saved ``.md`` is clean
    regardless of whether the model followed the no-LaTeX instruction. It is not
    a full LaTeX parser — it targets the constructs this skill actually produces.
    """
    import re

    s = text
    # Fractions first, before braces are stripped: \frac{a}{b} -> (a)/(b)
    s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
    # Matrix/array environments: turn \begin{bmatrix}..\end{bmatrix} into plain
    # brackets so the leftover-command strip below doesn't leave "bmatrix".
    # Run before the row/column separators and the generic backslash strip.
    s = re.sub(r"\\begin\s*\{[^{}]*\}", "[", s)
    s = re.sub(r"\\end\s*\{[^{}]*\}", "]", s)
    # Row separator "\\" (optionally with a [len] spec) -> "; ", before the
    # spacing rule below can chew a backslash off the pair. Eat surrounding
    # whitespace so "0 \\ 1" becomes "0; 1", not "0 ; 1".
    s = re.sub(r"\s*\\\\(?:\[[^\]]*\])?\s*", "; ", s)
    # Column separator "&" -> ", " (eat surrounding whitespace)
    s = re.sub(r"\s*&\s*", ", ", s)
    # Symbol commands -> Unicode
    symbols = {
        r"\^\\circ": "°",
        r"\\circ": "°",
        r"\\degree": "°",
        r"\\times": "×",
        r"\\cdot": "·",
        r"\\div": "÷",
        r"\\rightarrow": "→",
        r"\\to": "→",
        r"\\Rightarrow": "⇒",
        r"\\leq": "≤",
        r"\\geq": "≥",
        r"\\approx": "≈",
        r"\\neq": "≠",
        r"\\pm": "±",
        r"\\Delta": "Δ",
        r"\\Sigma": "Σ",
        r"\\sum": "Σ",
    }
    for pat, rep in symbols.items():
        s = re.sub(pat, rep, s)
    # \text{...}, \mathrm{...}, etc. -> their contents
    s = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|mathsf|operatorname)\s*\{([^{}]*)\}",
        r"\1",
        s,
    )
    # Spacing commands (\, \; \: \! and backslash-space) -> nothing.
    # These are the stray "random commas" once the backslash is dropped.
    s = re.sub(r"\\[,;:!\s]", "", s)
    # Subscripts / superscripts
    s = re.sub(r"_\{([^{}]*)\}", r"\1", s)  # _{18} -> 18
    s = re.sub(r"\^\{([^{}]*)\}", r"^\1", s)  # ^{2}  -> ^2
    s = s.replace("^*", "*")  # B^* -> B*, B_c^* -> B_c*
    s = re.sub(r"_(\d)", r"\1", s)  # _2    -> 2 (digits only, so
    #                                              snake_case words are untouched)
    # Math delimiters \( \) \[ \] and $...$
    s = re.sub(r"\\[()\[\]]", "", s)
    s = s.replace("$", "")
    # Drop any leftover backslash commands (e.g. \left, \right, \quad)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    # Remove now-orphaned braces and collapse runs of spaces
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s


def _export_markdown(
    final_text: str,
    cwd: str,
    source_paths: list[str],
    *,
    title: str,
    subdir: str,
    suffix: str,
    label: str,
) -> None:
    """Save a model answer to ``<cwd>/<subdir>/<stem>_<suffix>_<ts>.md``.

    Deterministic post-step: the harness writes the file itself, so it does not
    depend on the model remembering to call a write tool. LaTeX is flattened to
    plain text on the way out. Failures are reported but never abort the turn.
    """
    from datetime import datetime

    stem = Path(source_paths[0]).stem if source_paths else "exercise"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sources = ", ".join(Path(p).name for p in source_paths) if source_paths else "(none)"
    header = f"# {title}: {stem}\n\n- Source: {sources}\n- Generated: {ts}\n\n---\n\n"
    try:
        out_dir = Path(cwd) / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stem}_{suffix}_{ts}.md"
        out_path.write_text(header + _latex_to_plaintext(final_text), encoding="utf-8")
        console.print(f"[dim]{label} exported: {out_path}[/dim]")
    except OSError as exc:
        console.print(f"[yellow]Could not export {label.lower()} markdown: {exc}[/yellow]")


def _export_review_markdown(final_text: str, cwd: str, source_paths: list[str]) -> None:
    """Save an exercise-review answer to ``<cwd>/reviews/<stem>_review_<ts>.md``."""
    _export_markdown(
        final_text,
        cwd,
        source_paths,
        title="Exercise review",
        subdir="reviews",
        suffix="review",
        label="Review",
    )


def _export_transcription_markdown(final_text: str, cwd: str, source_paths: list[str]) -> None:
    """Save a transcription to ``<cwd>/transcriptions/<stem>_transcription_<ts>.md``."""
    _export_markdown(
        final_text,
        cwd,
        source_paths,
        title="Transcription",
        subdir="transcriptions",
        suffix="transcription",
        label="Transcription",
    )


def _project_prompt(config: AgentConfig, prompt: str) -> str:
    """Wrap *prompt* with project context when a project is active, else return it."""
    if not config.project_id:
        return prompt
    from ci2lab.ui.projects import project_prompt

    return project_prompt(config.project_id, prompt)
