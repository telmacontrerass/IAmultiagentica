#!/usr/bin/env python3
"""Compara varias configs OpenCode contra una matriz de casos de seguridad."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.security.opencode_config_comparison import (
    export_config_comparison_report,
    resolve_config_bundles,
    run_config_comparison,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        action="append",
        type=Path,
        default=[],
        dest="configs",
        help="Archivo JSON de config (repetible)",
    )
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Preset integrado (repetible)",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Directorio base de runs (default: runs)",
    )
    args = parser.parse_args()

    if not args.configs and not args.preset:
        print(
            json.dumps({"error": "Indique al menos un --config o --preset"}),
            file=sys.stderr,
        )
        return 1

    try:
        bundles = resolve_config_bundles(
            config_paths=args.configs,
            presets=args.preset,
        )
        rows = run_config_comparison(bundles, args.workspace.resolve())
        export = export_config_comparison_report(
            rows,
            workspace=args.workspace.resolve(),
            runs_dir=args.runs_dir,
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "output_dir": str(export.output_dir),
                "csv": str(export.csv_path),
                "markdown": str(export.markdown_path),
                "rows": len(rows),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
