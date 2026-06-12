#!/usr/bin/env python3
"""P2.10 — Harness Write Reliability Eval (live con modelos locales)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.evals.harness_write_eval import (  # noqa: E402
    DEFAULT_MODELS,
    PASS,
    default_live_cases,
    run_live_suite,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        help="Tags Ollama (ej. llama3.1:8b qwen3:4b)",
    )
    parser.add_argument(
        "--workspace-tmp",
        type=Path,
        default=ROOT / "tmp" / "harness_write_eval",
        help="Directorio base para workspaces temporales por caso/modelo",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "artifacts" / "harness_write_eval",
        help="Directorio base de artefactos (results.csv, summary.json)",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="IDs de caso (default: todos los live iniciales)",
    )
    parser.add_argument(
        "--tool-mode",
        choices=["native", "fenced"],
        default=None,
        help="Override de tool_mode para todos los modelos",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Segundos por caso/modelo",
    )
    args = parser.parse_args(argv)

    all_cases = default_live_cases()
    if args.cases:
        wanted = set(args.cases)
        cases = [c for c in all_cases if c.case_id in wanted]
        missing = wanted - {c.case_id for c in cases}
        if missing:
            parser.error(f"Casos desconocidos: {', '.join(sorted(missing))}")
    else:
        cases = all_cases

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    output_dir = args.output_root.resolve() / stamp
    workspace_tmp = args.workspace_tmp.resolve()

    results = run_live_suite(
        models=args.models,
        workspace_tmp=workspace_tmp,
        output_dir=output_dir,
        cases=cases,
        timeout_s=args.timeout,
        tool_mode=args.tool_mode,
    )

    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print(json.dumps(summary["pattern_hint"], indent=2, ensure_ascii=True))
    print(json.dumps(summary["counts"], indent=2, ensure_ascii=True))
    print(f"Artefactos: {output_dir}")
    return 0 if all(r.verdict == PASS for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
