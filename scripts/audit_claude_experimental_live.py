#!/usr/bin/env python3
"""Auditoría live de claude_experimental contra modelos Ollama locales."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.security.claude_live_audit import (  # noqa: E402
    DEFAULT_MODELS,
    SECURITY_FAIL,
    run_full_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="Tag Ollama (ej. llama3.1:8b)")
    parser.add_argument(
        "--tool-mode",
        choices=["native", "fenced"],
        default="native",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ejecutar llama3.1:8b (native) y qwen3:4b (fenced)",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Segundos por caso")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "audit" / "live_claude",
        help="Directorio base de salida",
    )
    args = parser.parse_args(argv)

    if args.all:
        models = list(DEFAULT_MODELS)
    elif args.model:
        models = [(args.model, args.tool_mode)]
    else:
        parser.error("Indique --model o --all")

    with tempfile.TemporaryDirectory(prefix="ci2lab_claude_audit_") as tmp:
        base = Path(tmp)
        results, out_dir, _ws = run_full_audit(
            models=models,
            base_dir=base,
            repo_root=ROOT,
            timeout_s=args.timeout,
            output_root=args.output_root.resolve(),
        )

    summary_path = out_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print(json.dumps(summary["counts"], indent=2, ensure_ascii=False))
    print(f"Artefactos: {out_dir}")
    return 1 if any(r.observed_status == SECURITY_FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
