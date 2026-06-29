"""models commands (recommend, install, run)."""

from __future__ import annotations

import argparse
import json
import subprocess

from rich.table import Table

from ci2lab.cli.commands.hardware import _print_memory_budget_context
from ci2lab.config import load_config
from ci2lab.console import console
from ci2lab.contracts import HardwareProfile, ModelSpec
from ci2lab.hardware import scan_hardware
from ci2lab.router.catalog import load_model_catalog
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
