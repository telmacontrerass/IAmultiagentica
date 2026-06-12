#!/usr/bin/env python3
"""Exporta configs OpenCode/CI2Lab desde preset o archivo de entrada."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci2lab.security.opencode_config_io import (
    bundle_from_preset,
    export_ci2lab_format,
    export_opencode_format,
    export_warnings_for_permission,
    extract_opencode_permission,
    load_opencode_config,
    write_json_output,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        default=None,
        help="Preset opencode (opencode_dev, opencode_paranoid, opencode_external_allowed)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Archivo ci2lab.json u opencode.json de entrada",
    )
    parser.add_argument(
        "--format",
        required=True,
        choices=["opencode", "ci2lab"],
        help="Formato de salida",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Archivo de salida (default: stdout)",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace para rutas relativas de --output",
    )
    args = parser.parse_args()

    if (args.preset is None) == (args.input is None):
        print(
            json.dumps({"error": "Indique exactamente uno de --preset o --input"}),
            file=sys.stderr,
        )
        return 1

    try:
        preset_name: str | None = None
        if args.preset is not None:
            bundle = bundle_from_preset(args.preset)
            permission = bundle.normalized_permission
            preset_name = args.preset
        else:
            assert args.input is not None
            raw = load_opencode_config(args.input)
            permission = extract_opencode_permission(raw)
            if args.format == "ci2lab":
                sec = raw.get("security")
                if isinstance(sec, dict) and isinstance(sec.get("permission_preset"), str):
                    preset_name = sec["permission_preset"]

        if args.format == "opencode":
            payload = export_opencode_format(permission)
        else:
            payload = export_ci2lab_format(
                permission,
                permission_preset=preset_name if preset_name else None,
            )

        warnings = export_warnings_for_permission(permission)
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

        write_json_output(
            payload,
            output=args.output,
            workspace=args.workspace,
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
