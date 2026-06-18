"""skills command."""

from __future__ import annotations

import argparse
import json

from rich.table import Table

from ci2lab.console import console
from ci2lab.config import Ci2LabConfig
from ci2lab.harness.skills.loader import load_skills


def _cmd_skills(args: argparse.Namespace, runtime: Ci2LabConfig) -> int:
    cwd = str(getattr(args, "workspace", None) or runtime.workspace or ".")
    rows = [
        {
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "model_invocable": not skill.disable_model_invocation,
            "user_invocable": skill.user_invocable,
            "allowed_tools": skill.allowed_tools,
            "path": str(skill.path),
        }
        for skill in sorted(load_skills(cwd).values(), key=lambda item: item.name)
    ]
    if args.json:
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return 0
    if not rows:
        console.print("No skills found.")
        return 0

    table = Table(title=f"Skills for {cwd}")
    table.add_column("Name")
    table.add_column("Source")
    table.add_column("Model")
    table.add_column("User")
    table.add_column("Allowed tools")
    table.add_column("Description")
    for row in rows:
        table.add_row(
            row["name"],
            row["source"],
            "yes" if row["model_invocable"] else "no",
            "yes" if row["user_invocable"] else "no",
            ", ".join(row["allowed_tools"]) or "-",
            row["description"],
        )
    console.print(table)
    return 0
