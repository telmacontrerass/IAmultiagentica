#!/usr/bin/env python3
"""Compara decisiones de seguridad entre ci2lab y opencode_experimental."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.security.comparison import (
    export_comparison_report,
    format_comparison_table,
    row_to_dict,
    run_comparison,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=ROOT,
        help="Directorio workspace para casos sinteticos",
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Subcarpeta de runs bajo workspace (default: runs)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida JSON por stdout en lugar de tabla",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="No escribir CSV/Markdown en runs/security_comparison/",
    )
    args = parser.parse_args()

    ws = args.workspace.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "inside.txt").write_text("inside\n", encoding="utf-8")
    outside_dir = ws.parent / "outside_cmp"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("outside\n", encoding="utf-8")
    dotenv = ws / ".env"
    dotenv.write_text("SECRET=1\n", encoding="utf-8")

    rows = run_comparison(ws, outside_path=outside_file, env_path=dotenv)
    passed = sum(1 for r in rows if r.passed)

    if args.json:
        print(json.dumps([row_to_dict(r) for r in rows], indent=2, ensure_ascii=False))
    else:
        print(format_comparison_table(rows))

    if not args.no_export:
        export_result = export_comparison_report(
            rows,
            workspace=ws,
            runs_dir=args.runs_dir,
        )
        print("")
        print(f"CSV: {export_result.csv_path}")
        print(f"Markdown: {export_result.markdown_path}")

    failed = [r for r in rows if not r.passed]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
