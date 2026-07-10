#!/usr/bin/env python3
"""Evalúa la puerta de seguridad sin ejecutar la tool (dry gate)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.security.engine import (
    DEFAULT_SECURITY_ENGINE,
    UnknownSecurityEngineError,
    normalize_security_engine,
)
from ci2lab.security.gate_check import evaluate_security_gate, load_permission_config
from ci2lab.security.opencode_config_io import load_opencode_config_bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=f"Motor por defecto: {DEFAULT_SECURITY_ENGINE}.",
    )
    parser.add_argument(
        "--engine",
        default=DEFAULT_SECURITY_ENGINE,
        metavar="ENGINE",
        help=(
            f"Motor de seguridad (default: {DEFAULT_SECURITY_ENGINE}). "
            "Valores: ci2lab_guard, ci2lab, opencode_experimental."
        ),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--tool", required=True, help="Nombre de la tool")
    parser.add_argument("--target", required=True, help="Comando o ruta objetivo")
    parser.add_argument(
        "--permission-config",
        type=Path,
        default=None,
        help="JSON con permission (root-level o security.permission)",
    )
    parser.add_argument(
        "--opencode-config",
        type=Path,
        default=None,
        help="Config estilo opencode.json (importa, normaliza y evalúa)",
    )
    parser.add_argument(
        "--show-effective-config",
        action="store_true",
        help="Incluir effective_permission en la salida JSON",
    )
    parser.add_argument("--yes", action="store_true", help="auto_confirm (--yes)")
    parser.add_argument(
        "--security-profile",
        default="standard",
        help="Perfil de seguridad (strict, standard, dev, audit)",
    )
    args = parser.parse_args()

    if args.permission_config is not None and args.opencode_config is not None:
        print(
            json.dumps(
                {"error": "Use solo uno de --permission-config o --opencode-config"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    try:
        engine = normalize_security_engine(args.engine)
        perm = None
        bundle = None
        if args.opencode_config is not None:
            bundle = load_opencode_config_bundle(args.opencode_config)
        elif args.permission_config is not None:
            perm = load_permission_config(args.permission_config)

        result = evaluate_security_gate(
            engine=engine,
            workspace=str(args.workspace.resolve()),
            tool=args.tool,
            target=args.target,
            permission_config=perm,
            config_bundle=bundle,
            auto_confirm=args.yes,
            security_profile=args.security_profile,
            show_effective_config=args.show_effective_config,
        )
    except UnknownSecurityEngineError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
