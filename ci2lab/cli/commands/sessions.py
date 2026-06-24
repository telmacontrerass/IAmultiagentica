"""sessions command."""

from __future__ import annotations

import argparse
import json

from rich.table import Table

from ci2lab.console import console


def _cmd_sessions(args: argparse.Namespace) -> int:
    from ci2lab.harness.session import list_sessions

    rows = list_sessions()
    if args.json:
        console.print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        console.print("No saved sessions.")
        return 0
    table = Table(title="Sessions ~/.ci2lab/sessions")
    table.add_column("Title")
    table.add_column("ID")
    table.add_column("Model")
    table.add_column("CWD")
    table.add_column("Updated")
    for row in rows:
        table.add_row(
            row.get("title") or "Conversation",
            row["id"],
            row["model"],
            row["cwd"][:40],
            row["updated_at"][:19],
        )
    console.print(table)
    return 0
