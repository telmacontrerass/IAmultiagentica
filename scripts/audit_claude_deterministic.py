#!/usr/bin/env python3
"""Auditoría determinista P3.0.1 — ci2lab_guard sin LLM."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.security.claude_deterministic_matrix import (  # noqa: E402
    export_deterministic_report,
    matrix_has_security_fail,
    run_full_deterministic_matrix,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "audit" / "deterministic_claude",
        help="Directorio base de salida",
    )
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = args.output_root.resolve() / stamp

    with tempfile.TemporaryDirectory(prefix="ci2lab_guard_det_") as tmp:
        gate_results, dispatch_results, ws = run_full_deterministic_matrix(
            Path(tmp),
            repo_root=ROOT,
        )
        paths = export_deterministic_report(
            gate_results,
            dispatch_results,
            out_dir=out_dir,
            workspace_root=ws.root,
            outside_secret=ws.outside_secret,
        )

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    print(json.dumps(summary["overall"], indent=2, ensure_ascii=False))
    print(json.dumps({"gate": summary["gate"], "dispatch": summary["dispatch"]}, indent=2))
    print(f"Artefactos: {out_dir}")
    return 1 if matrix_has_security_fail(gate_results, dispatch_results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
