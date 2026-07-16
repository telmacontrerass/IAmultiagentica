"""models commands (recommend, install, run)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from rich.table import Table

from ci2lab.cli.commands.hardware import _print_memory_budget_context
from ci2lab.config import load_config
from ci2lab.console import console
from ci2lab.contracts import HardwareProfile, ModelSpec
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import load_model_catalog
from ci2lab.router.gguf_import.adapted_validation import validate_adapted_glm
from ci2lab.router.gguf_import.adapter_manifest import get_adapter, load_adapter_catalog
from ci2lab.router.gguf_import.benchmark import ADAPTED_TOOLS_SCENARIOS
from ci2lab.router.gguf_import.capabilities import (
    ImportedCapabilities,
    InferenceCapability,
    ToolCallingCapability,
)
from ci2lab.router.gguf_import.inspector import inspect_gguf
from ci2lab.router.gguf_import.ollama_identity import (
    decide_identity,
    expected_identity,
    safe_rollback_created_model,
    snapshot_ollama_model,
    verify_post_create,
)
from ci2lab.router.gguf_import.robust_benchmark import run_robust_suite
from ci2lab.router.gguf_import.smoke_runner import create_smoke_transport, run_smoke_suite
from ci2lab.router.gguf_import.source import GGUFSourceResolver
from ci2lab.router.gguf_import.validation import create_run_dir, validate_llama_cpp
from ci2lab.router.imported_models import (
    build_imported_profile,
    create_ollama_model,
    find_imported_model_by_tag,
    load_imported_model_registry,
    render_ollama_modelfile,
    save_imported_model_profile,
    verify_ollama_inference,
)
from ci2lab.router.intent import classify_intent
from ci2lab.router.recommend import (
    ScoredRecommendation,
    build_display_recommendations,
    model_fits,
    recommend_download_plan,
    recommendation_pool_size,
    score_recommendations,
)
from ci2lab.runtime.ollama import fetch_installed_model_names


def _cmd_models_recommend(args: argparse.Namespace) -> int:
    """Recommend catalog models, either for a query or as a general download plan.

    Args:
        args: Parsed CLI arguments (optional ``model_prompt``, ``--json`` and
            ``--limit``).

    Returns:
        Process exit code: ``0`` on success, ``1`` if no model fits the budget.
    """
    profile = scan_hardware()
    prompt = " ".join(args.model_prompt)
    if prompt:
        return _focused_recommend_command(
            prompt=prompt,
            profile=profile,
            json_output=args.json,
            limit=args.limit,
        )
    return _download_plan_command(profile=profile, json_output=args.json)


def _cmd_models_install(args: argparse.Namespace) -> int:
    """Print the pull/run/chat commands for an allowed catalog model.

    Args:
        args: Parsed CLI arguments (the model ``id``/tag and ``--json``).

    Returns:
        Process exit code: ``0`` on success, ``1`` if the model is not allowed.
    """
    profile = scan_hardware()
    model = _resolve_allowed_model(args.model, profile=profile)
    if model is None:
        return 1

    commands = _install_commands(model)
    if args.json:
        console.print_json(
            json.dumps(
                {
                    "id": model.id,
                    "display_name": model.display_name,
                    "ollama_tag": model.ollama_tag,
                    "commands": commands,
                }
            )
        )
        return 0

    console.print(f"[bold]Chosen model:[/bold] {model.display_name}")
    console.print(f"[bold]Ollama:[/bold] {model.ollama_tag}\n")
    console.print("[bold]1. Install/download the model:[/bold]")
    console.print(f"  {commands['pull']}")
    console.print("\n[bold]2. Open a direct chat with Ollama:[/bold]")
    console.print(f"  {commands['ollama_run']}")
    console.print("\n[bold]3. Open an agentic chat from ci2lab:[/bold]")
    console.print(f"  {commands['ci2lab_chat']}")
    return 0


def _cmd_models_run(args: argparse.Namespace) -> int:
    """Open an allowed catalog model directly with ``ollama run``.

    Args:
        args: Parsed CLI arguments (the model ``id``/tag).

    Returns:
        Process exit code: the ``ollama run`` return code, or ``1`` if the model
        is not allowed or the ``ollama`` executable is missing.
    """
    profile = scan_hardware()
    model = _resolve_allowed_model(args.model, profile=profile)
    if model is None:
        return 1

    console.print(f"[bold]Opening:[/bold] {model.display_name} ({model.ollama_tag})")
    console.print("[dim]Exit with /bye or Ctrl+C.[/dim]\n")
    try:
        completed = subprocess.run(["ollama", "run", model.ollama_tag], check=False)
    except FileNotFoundError:
        console.print("[red]Cannot find the `ollama` command.[/red]")
        console.print("Install Ollama and then run:")
        console.print(f"  {_install_commands(model)['pull']}")
        return 1
    return completed.returncode


def _cmd_models_import_gguf(args: argparse.Namespace) -> int:
    """Import one already-downloaded GGUF file into Ollama and CI2Lab metadata."""
    gguf_path = Path(args.path).expanduser()
    if not gguf_path.is_file():
        console.print(f"[red]GGUF file not found:[/red] {gguf_path}")
        return 1
    try:
        source = GGUFSourceResolver().resolve_local(gguf_path, repo_id=args.repo)
        inspection = inspect_gguf(source.local_path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Invalid GGUF: {exc}[/red]")
        console.print("[bold]State:[/bold] IMPORT_FAILED")
        return 1
    resolved_gguf_path = str(source.local_path)

    try:
        profile = build_imported_profile(
            model_id=args.id,
            ollama_tag=args.ollama_tag,
            repo=args.repo,
            filename=args.file,
            local_path=resolved_gguf_path,
            family=args.family,
            template_id=args.template,
            context_length=args.ctx,
            tool_mode=args.tool_mode,
        )
        profile = replace(
            profile,
            source={
                **profile.source,
                "sha256": source.sha256,
                "size_bytes": source.size_bytes,
                "architecture": inspection.architecture or "unknown",
                "quantization": inspection.quantization,
                "template_sha256": inspection.template_analysis.template_sha256,
                "inspection_tool": inspection.inspection_tool,
            },
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if args.dry_run:
        sys.stdout.write(render_ollama_modelfile(profile))
        console.print("[bold]State:[/bold] dry-run; registry unchanged")
        return 0

    modelfile = render_ollama_modelfile(profile)
    identity = expected_identity(profile, modelfile)
    previous_profile = find_imported_model_by_tag(profile.ollama_tag)
    registered_identity = (
        previous_profile.source.get("ollama_identity")
        if previous_profile and isinstance(previous_profile.source.get("ollama_identity"), dict)
        else None
    )
    before = snapshot_ollama_model(profile.ollama_tag)
    decision = decide_identity(identity, before, registered_identity)
    if decision.state == "IMPORT_CONFLICT":
        console.print("[red]State: IMPORT_CONFLICT[/red]")
        for difference in decision.differences:
            console.print(f"- {difference}")
        console.print("Ollama and the CI2Lab registry were not modified.")
        return 1
    if decision.state == "EXTERNAL_MODEL_UNTRACKED":
        console.print("[red]State: EXTERNAL_MODEL_UNTRACKED[/red]")
        console.print("The tag exists without a sufficiently traced CI2Lab identity.")
        return 1
    if decision.state == "ALREADY_IMPORTED_EQUIVALENT":
        console.print("[green]State: ALREADY_IMPORTED_EQUIVALENT[/green]")
        console.print("No Ollama model or registry entry was changed.")
        return 0

    try:
        _modelfile, completed = create_ollama_model(profile, dry_run=False)
    except FileNotFoundError:
        console.print("[red]Cannot find the `ollama` command.[/red]")
        return 1
    if completed is None:
        return 1
    if completed.stdout:
        console.print(completed.stdout.strip())
    if completed.stderr:
        console.print(completed.stderr.strip())
    if completed.returncode != 0:
        console.print(f"[red]ollama create failed with exit code {completed.returncode}.[/red]")
        console.print("[bold]State:[/bold] IMPORT_FAILED")
        return completed.returncode

    after = snapshot_ollama_model(profile.ollama_tag)
    post_differences = verify_post_create(identity, after)
    if post_differences:
        rolled_back = safe_rollback_created_model(
            profile.ollama_tag, before=before, after_creation=after
        )
        console.print("[red]ollama show is inconsistent with the requested identity.[/red]")
        for difference in post_differences:
            console.print(f"- {difference}")
        state = "IMPORT_FAILED" if rolled_back else "IMPORT_PARTIALLY_COMPLETED"
        console.print(f"[bold]State:[/bold] {state}")
        return 1
    try:
        inference = verify_ollama_inference(profile)
    except (OSError, subprocess.TimeoutExpired) as exc:
        rolled_back = safe_rollback_created_model(
            profile.ollama_tag, before=before, after_creation=after
        )
        console.print(f"[red]Minimal inference failed: {exc}[/red]")
        state = "IMPORT_FAILED" if rolled_back else "IMPORT_PARTIALLY_COMPLETED"
        console.print(f"[bold]State:[/bold] {state}")
        return 1
    if inference.returncode != 0 or inference.stdout.strip().strip(". ").upper() != "OK":
        rolled_back = safe_rollback_created_model(
            profile.ollama_tag, before=before, after_creation=after
        )
        console.print("[red]Minimal inference did not return exactly OK; registry unchanged.[/red]")
        state = "IMPORT_FAILED" if rolled_back else "IMPORT_PARTIALLY_COMPLETED"
        console.print(f"[bold]State:[/bold] {state}")
        return 1
    profile = replace(
        profile,
        source={**profile.source, "ollama_identity": identity.to_dict()},
        verification={**profile.verification, "created": True, "verified": True},
        capabilities=ImportedCapabilities(
            inference=InferenceCapability(True, "ollama", profile.context_length)
        ),
    )

    if args.run_smoke:
        if not args.smoke_protocol:
            console.print("[red]--run-smoke requires --smoke-protocol[/red]")
            console.print("[bold]State:[/bold] IMPORT_PARTIALLY_COMPLETED")
            return 1
        profile = replace(
            profile,
            capabilities=replace(
                profile.capabilities,
                tool_calling=ToolCallingCapability(
                    protocol=args.smoke_protocol,
                    parser=(
                        "openai_tool_calls"
                        if args.smoke_protocol == "native"
                        else (args.smoke_adapter or "fenced_v1")
                    ),
                    adapter=args.smoke_adapter,
                    template_source=(
                        "family_adapter"
                        if args.smoke_protocol == "adapted_native"
                        else "gguf_embedded"
                    ),
                    selection_reason="configured for post-import empirical smoke",
                    evidence_level="configured",
                ),
            ),
        )
        evidence_dir = create_run_dir(Path(args.runs_dir))
        transport = create_smoke_transport(
            profile,
            backend=args.smoke_backend,
            evidence_dir=evidence_dir,
            model_path=Path(profile.local_path) if args.smoke_backend == "llama-cpp" else None,
            llama_server_path=(Path(args.llama_server_path) if args.llama_server_path else None),
        )
        artifact, profile = run_smoke_suite(
            profile,
            transport,
            evidence_dir=evidence_dir,
            request_timeout=args.request_timeout,
            promote=True,
            backend_name=args.smoke_backend,
        )
        console.print(f"[bold]Smoke evidence:[/bold] {evidence_dir}")
        if artifact["capabilities"]["tool_calling_verified"]:
            console.print("[bold]State:[/bold] IMPORTED_TOOLS_VERIFIED")

    registry_path = save_imported_model_profile(profile)
    console.print(f"[green]Imported model:[/green] {profile.id}")
    console.print(f"[bold]Ollama tag:[/bold] {profile.ollama_tag}")
    console.print(f"[bold]CI2Lab registry:[/bold] {registry_path}")
    console.print(f"[bold]SHA-256:[/bold] {source.sha256}")
    console.print("[bold]Inference:[/bold] verified")
    console.print("[bold]Tool calling:[/bold] not verified")
    console.print("[bold]State:[/bold] IMPORTED_AND_VERIFIED")
    return 0


def _cmd_models_gguf_import_smoke(args: argparse.Namespace) -> int:
    profile = find_imported_model_by_tag(args.model)
    if profile is None:
        console.print(f"[red]Imported profile not found:[/red] {args.model}")
        return 1
    evidence_dir = create_run_dir(Path(args.runs_dir))
    try:
        transport = create_smoke_transport(
            profile,
            backend=args.backend,
            evidence_dir=evidence_dir,
            model_path=Path(args.model_path) if args.model_path else None,
            llama_server_path=Path(args.llama_server_path) if args.llama_server_path else None,
            context_length=args.context_length,
            backend_url=args.backend_url,
        )
        artifact, promoted = run_smoke_suite(
            profile,
            transport,
            evidence_dir=evidence_dir,
            request_timeout=args.request_timeout,
            promote=not args.no_promote,
            scenario_ids=set(args.scenario) if args.scenario else None,
            backend_name=args.backend,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        console.print(f"[red]Smoke failed: {exc}[/red]")
        console.print(f"[bold]Evidence:[/bold] {evidence_dir}")
        return 1
    capabilities = artifact["capabilities"]
    console.print(f"[bold]Model:[/bold] {profile.id}")
    console.print(f"[bold]Tag:[/bold] {profile.ollama_tag}")
    console.print(f"[bold]Protocol:[/bold] {artifact['protocol']}")
    console.print(f"[bold]Inference:[/bold] {capabilities['inference_verified']}")
    console.print(f"[bold]Tools:[/bold] {capabilities['tool_calling_verified']}")
    console.print(f"[bold]Multiround:[/bold] {capabilities['multiround_verified']}")
    console.print(f"[bold]Write:[/bold] {capabilities['write_verified']}")
    console.print(f"[bold]Confinement:[/bold] {capabilities['workspace_confinement_verified']}")
    console.print(
        f"[bold]Untrusted content:[/bold] {capabilities['untrusted_content_resistance_verified']}"
    )
    console.print(f"[bold]Profile updated:[/bold] {not args.no_promote}")
    console.print(f"[bold]Evidence:[/bold] {evidence_dir}")
    technical = all(
        capabilities[key]
        for key in (
            "inference_verified",
            "tool_calling_verified",
            "multiround_verified",
            "write_verified",
            "complex_schema_verified",
            "workspace_confinement_verified",
        )
    )
    if args.scenario and args.no_promote:
        technical = all(item["passed"] for item in artifact["attempts"])
    if technical and promoted.capabilities.tool_calling.verified:
        console.print("[bold]State:[/bold] IMPORTED_TOOLS_VERIFIED")
    return 0 if technical else 1


def _cmd_models_list(args: argparse.Namespace) -> int:
    """List machine-local imported profiles (aliases, tags and protocol defaults)."""
    profiles = load_imported_model_registry()
    if args.json:
        console.print_json(json.dumps({"models": [profile.to_dict() for profile in profiles]}))
        return 0
    if not profiles:
        console.print("[yellow]No imported model profiles registered.[/yellow]")
        return 0
    table = Table(title="Imported CI2Lab models")
    table.add_column("Alias")
    table.add_column("Ollama tag")
    table.add_column("Family")
    table.add_column("Context")
    table.add_column("Tool mode")
    for profile in profiles:
        table.add_row(
            profile.id,
            profile.ollama_tag,
            profile.family,
            str(profile.context_length),
            profile.tool_mode,
        )
    console.print(table)
    return 0


def _cmd_models_inspect_gguf(args: argparse.Namespace) -> int:
    """Inspect a local GGUF without changing Ollama or CI2Lab registries."""
    try:
        source = GGUFSourceResolver().resolve_local(args.model_path)
        inspection = inspect_gguf(source.local_path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    payload = {"source": source.to_dict(), "inspection": inspection.to_dict()}
    if args.output_dir:
        run_dir = create_run_dir(Path(args.output_dir))
        (run_dir / "metadata.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if inspection.chat_template:
            (run_dir / "original_template.jinja").write_text(
                inspection.chat_template, encoding="utf-8"
            )
        console.print(f"[bold]Evidence:[/bold] {run_dir}")
    console.print_json(json.dumps(payload, ensure_ascii=False, default=str))
    return 0


def _cmd_models_validate_gguf(args: argparse.Namespace) -> int:
    """Run the isolated llama.cpp candidate; never register or create a model."""
    try:
        run_dir, gates = validate_llama_cpp(
            Path(args.model_path),
            binary=args.llama_server_path,
            context_length=args.context_length,
            runs_root=Path(args.runs_dir),
            request_timeout=args.request_timeout,
            startup_timeout=args.startup_timeout,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[bold]Evidence:[/bold] {run_dir}")
    console.print_json(json.dumps(gates.__dict__))
    return 0 if gates.final_state == "passed" else 1


def _cmd_models_validate_gguf_adapted(args: argparse.Namespace) -> int:
    """Validate only the explicit experimental GLM Jinja adapter candidate."""
    run_dir, gates = validate_adapted_glm(
        Path(args.model_path),
        binary=Path(args.llama_server_path),
        context_length=args.context_length,
        runs_root=Path(args.runs_dir),
        request_timeout=args.request_timeout,
        startup_timeout=args.startup_timeout,
    )
    console.print(f"[bold]Evidence:[/bold] {run_dir}")
    console.print_json(json.dumps(asdict(gates)))
    return 0 if gates.final_state == "adapted_tools_passed" else 1


def _cmd_models_adapters(args: argparse.Namespace) -> int:
    """List/inspect declarations without enabling them for stable model selection."""
    payload: object
    if args.adapter_command == "list":
        payload = [
            {
                "id": item.id,
                "version": item.version,
                "status": item.status,
                "enabled": item.enabled,
                "mode": item.adapted_tool_mode,
            }
            for item in load_adapter_catalog()
        ]
    elif args.adapter_command == "inspect":
        payload = get_adapter(args.adapter_id).to_dict()
    else:
        payload = [asdict(item) for item in ADAPTED_TOOLS_SCENARIOS]
    console.print_json(json.dumps(payload))
    return 0


def _cmd_models_benchmark_gguf_adapter(args: argparse.Namespace) -> int:
    """Run the explicit live robust-tools suite without profile promotion."""
    if args.repetitions < 1:
        console.print("[red]--repetitions must be positive[/red]")
        return 1
    run_dir, aggregate = run_robust_suite(
        Path(args.model_path),
        binary=Path(args.llama_server_path),
        runs_root=Path(args.runs_dir),
        adapter_id=args.adapter,
        repetitions=args.repetitions,
        context_length=args.context_length,
        timeout=args.request_timeout,
    )
    console.print(f"[bold]Evidence:[/bold] {run_dir}")
    console.print_json(json.dumps(aggregate))
    return 0 if aggregate["robust_validation_passed"] else 1


def _install_commands(model: ModelSpec) -> dict[str, str]:
    """Return the ``pull``/``ollama_run``/``ci2lab_chat`` command strings for a model."""
    return {
        "pull": f"ollama pull {model.ollama_tag}",
        "ollama_run": f"ollama run {model.ollama_tag}",
        "ci2lab_chat": f"ci2lab --model {model.id} chat",
    }


def _resolve_allowed_model(model_name: str, *, profile: HardwareProfile) -> ModelSpec | None:
    """Resolve a catalog model by id/tag/name, ensuring it fits the budget.

    Prints an error and the table of allowed models when the name is unknown or
    the model is too large for the current inference budget.

    Args:
        model_name: User-supplied model identifier (catalog id, Ollama tag or
            display name; matched case-insensitively).
        profile: The detected hardware profile used to check that the model fits.

    Returns:
        The matching :class:`ModelSpec`, or ``None`` if unknown or too large.
    """
    normalized = model_name.strip().lower()
    models = load_model_catalog()
    exact = [
        model
        for model in models
        if normalized
        in {
            model.id.lower(),
            model.ollama_tag.lower(),
            model.display_name.lower(),
        }
    ]

    if not exact:
        console.print(f"[red]Unrecognized model:[/red] {model_name}")
        _print_allowed_models(profile)
        return None

    model = exact[0]
    if not model_fits(model, profile):
        console.print(
            f"[red]That model exists, but it does not fit on this machine:[/red] {model.display_name}"
        )
        console.print(
            f"Approximate budget for inference: [bold]{profile.inference_budget_gb:g} GB[/bold]."
        )
        _print_allowed_models(profile)
        return None

    return model


def _print_allowed_models(profile: HardwareProfile) -> None:
    """Print a table of catalog models that fit within the budget for ``profile``."""
    allowed = [model for model in load_model_catalog() if model_fits(model, profile)]
    if not allowed:
        console.print("[yellow]No catalog models fit within this budget.[/yellow]")
        return

    table = Table(title="Models allowed on this machine")
    table.add_column("Type this")
    table.add_column("Ollama")
    table.add_column("Name")
    for model in allowed:
        table.add_row(model.id, model.ollama_tag, model.display_name)
    console.print(table)


def _focused_recommend_command(
    *,
    prompt: str,
    profile: HardwareProfile,
    json_output: bool,
    limit: int,
) -> int:
    """Rank catalog models for a specific task prompt and print the results.

    Args:
        prompt: The task description to classify and score models against.
        profile: The detected hardware profile.
        json_output: When True, emit a JSON payload instead of a table.
        limit: Maximum number of recommendations to display.

    Returns:
        Process exit code: ``0`` on success, ``1`` if no model fits the budget.
    """
    intent = classify_intent(prompt)
    runtime = load_config()
    installed_names, ollama_error = fetch_installed_model_names(runtime.backend_url)
    pool = score_recommendations(
        prompt,
        profile=profile,
        limit=recommendation_pool_size(limit),
    )
    recommendations = build_display_recommendations(
        pool,
        installed_names,
        limit=limit,
    )

    if json_output:
        payload = {
            "hardware": profile.to_dict(),
            "intent": {
                "category": intent.category,
                "confidence": intent.confidence,
                "signals": intent.signals,
                "difficulty": intent.difficulty,
            },
            "ollama_error": ollama_error,
            "models": [
                {
                    "id": entry.item.model.id,
                    "display_name": entry.item.model.display_name,
                    "ollama_tag": entry.item.model.ollama_tag,
                    "reason": entry.item.reason,
                    "score": entry.item.total_score,
                    "fit_label": entry.item.fit_label,
                    "recommendation_status": entry.item.recommendation_status,
                    "theoretical_fit": entry.item.theoretical_fit,
                    "current_fit": entry.item.current_fit,
                    "requires_memory_cleanup": entry.item.requires_memory_cleanup,
                    "installed": entry.installed,
                    "installation_label": entry.installation_label,
                    "criteria": _criteria_payload(entry.item),
                }
                for entry in recommendations
            ],
        }
        console.print_json(json.dumps(payload))
        return 0

    console.print(f"Detected intent: [bold]{intent.category}[/bold]")
    _print_memory_budget_context(profile)
    if ollama_error:
        console.print("[yellow]Warning: could not query Ollama to mark installed models.[/yellow]")

    if not recommendations:
        console.print("[yellow]No catalog models fit within this budget.[/yellow]")
        return 1

    table = Table(title="Recommended models")
    table.add_column("Model")
    table.add_column("Ollama")
    table.add_column("Installation")
    table.add_column("Status")
    table.add_column("Score")
    table.add_column("Memory")
    table.add_column("Reason")
    for entry in recommendations:
        item = entry.item
        install_label = (
            f"[green]{entry.installation_label}[/green]"
            if entry.installed
            else entry.installation_label
        )
        table.add_row(
            item.model.display_name,
            item.model.ollama_tag,
            install_label,
            item.fit_label,
            str(item.total_score),
            _memory_summary(item),
            item.reason,
        )
    console.print(table)
    return 0


def _download_plan_command(*, profile: HardwareProfile, json_output: bool) -> int:
    """Print a general per-use-case download plan for the given hardware.

    Args:
        profile: The detected hardware profile.
        json_output: When True, emit a JSON payload instead of a table.

    Returns:
        Process exit code: ``0`` on success, ``1`` if no model fits the budget.
    """
    runtime = load_config()
    installed_names, ollama_error = fetch_installed_model_names(runtime.backend_url)
    plan = recommend_download_plan(profile=profile, installed_names=installed_names)

    if json_output:
        payload = {
            "hardware": profile.to_dict(),
            "ollama_error": ollama_error,
            "download_plan": [
                {
                    "use_cases": item.use_cases,
                    "id": item.recommendation.model.id,
                    "display_name": item.recommendation.model.display_name,
                    "ollama_tag": item.recommendation.model.ollama_tag,
                    "reason": item.recommendation.reason,
                    "score": item.recommendation.total_score,
                    "fit_label": item.recommendation.fit_label,
                    "recommendation_status": item.recommendation.recommendation_status,
                    "theoretical_fit": item.recommendation.theoretical_fit,
                    "current_fit": item.recommendation.current_fit,
                    "requires_memory_cleanup": item.recommendation.requires_memory_cleanup,
                    "installed": item.installed,
                    "installation_label": (
                        "Already installed" if item.installed else "To download"
                    ),
                    "criteria": _criteria_payload(item.recommendation),
                }
                for item in plan
            ],
        }
        console.print_json(json.dumps(payload))
        return 0

    _print_memory_budget_context(profile)
    if ollama_error:
        console.print("[yellow]Warning: could not query Ollama to mark installed models.[/yellow]")

    if not plan:
        console.print("[yellow]No catalog models fit within this budget.[/yellow]")
        return 1

    table = Table(title="Recommended models for your machine")
    table.add_column("Uses")
    table.add_column("Model")
    table.add_column("Ollama")
    table.add_column("Installation")
    table.add_column("Status")
    table.add_column("Score")
    table.add_column("Memory")
    table.add_column("Reason")
    for item in plan:
        recommendation = item.recommendation
        install_label = "[green]Already installed[/green]" if item.installed else "To download"
        table.add_row(
            ", ".join(item.use_cases),
            recommendation.model.display_name,
            recommendation.model.ollama_tag,
            install_label,
            recommendation.fit_label,
            str(recommendation.total_score),
            _memory_summary(recommendation),
            recommendation.reason,
        )
    console.print(table)
    return 0


def _criteria_payload(item: ScoredRecommendation) -> dict[str, float | str | bool]:
    """Return the per-criterion scoring breakdown as a JSON-serializable dict."""
    return {
        "quality": item.quality_score,
        "speed": item.speed_score,
        "fit": item.fit_score,
        "context": item.context_score,
        "memory_required_gb": item.memory_required_gb,
        "memory_budget_gb": item.memory_budget_gb,
        "remaining_memory_gb": item.remaining_memory_gb,
        "memory_usage_percent": item.memory_usage_percent,
        "memory_fit_status": item.memory_fit_status,
        "recommendation_status": item.recommendation_status,
        "theoretical_fit": item.theoretical_fit,
        "current_fit": item.current_fit,
        "requires_memory_cleanup": item.requires_memory_cleanup,
    }


def _memory_summary(item: ScoredRecommendation) -> str:
    """Return a short human-readable memory-usage summary for a recommendation."""
    return (
        f"uses ~{item.memory_required_gb:g} GB "
        f"({item.memory_usage_percent:g}%); "
        f"~{item.remaining_memory_gb:g} GB left"
    )
