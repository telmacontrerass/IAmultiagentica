"""Import/export y validación de configs estilo OpenCode (EXPERIMENTAL)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.security.opencode_permissions import OpenCodePermissionConfig, parse_opencode_permissions

_VALID_ACTIONS = frozenset({"allow", "ask", "deny"})

_SUPPORTED_OPENCODE_KEYS = frozenset({
    "*",
    "read",
    "edit",
    "write",
    "write_file",
    "edit_file",
    "bash",
    "shell",
    "grep",
    "glob",
    "list",
    "external_directory",
})

_EXTERNAL_ALLOW_WARNING = (
    "INSEGURO: external_directory=allow permite acceso fuera del workspace "
    "en opencode_experimental"
)


@dataclass(frozen=True)
class OpenCodeConfigBundle:
    """Resultado de cargar y normalizar una config OpenCode/CI2Lab."""

    config_source: str
    raw_config: dict[str, Any]
    permission: dict[str, Any]
    normalized_permission: dict[str, Any]
    unsupported_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_permission_config(self) -> OpenCodePermissionConfig:
        return parse_opencode_permissions(self.normalized_permission)


def load_opencode_config(path: str | Path) -> dict[str, Any]:
    """Carga JSON desde disco. Raises ValueError/FileNotFoundError si inválido."""
    raw_path = Path(path).expanduser().resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"No existe el archivo de configuración: {raw_path}")
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido en {raw_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"La configuración debe ser un objeto JSON: {raw_path}")
    return data


def extract_opencode_permission(config: dict[str, Any]) -> dict[str, Any]:
    """
    Extrae permission desde root-level o security.permission.

    Precedencia: security.permission > permission (root).
    """
    if not isinstance(config, dict):
        raise ValueError("config debe ser un objeto JSON.")

    security = config.get("security")
    if isinstance(security, dict):
        sec_perm = security.get("permission")
        if isinstance(sec_perm, dict):
            return dict(sec_perm)

    root_perm = config.get("permission")
    if isinstance(root_perm, dict):
        return dict(root_perm)

    if _looks_like_permission_map(config):
        return dict(config)

    raise ValueError(
        "No se encontró permission: use clave root 'permission' o 'security.permission'."
    )


def _looks_like_permission_map(data: dict[str, Any]) -> bool:
    markers = {"read", "edit", "bash", "external_directory", "*"}
    return any(key in data for key in markers)


def _normalize_action(value: str) -> str:
    action = value.strip().lower()
    if action not in _VALID_ACTIONS:
        raise ValueError(f"acción de permiso inválida: {value!r} (use allow|ask|deny)")
    return action


def normalize_opencode_permission(permission: dict[str, Any]) -> dict[str, Any]:
    """Normaliza valores allow/ask/deny y external_directory escalar."""
    if not isinstance(permission, dict):
        raise ValueError("permission debe ser un objeto JSON.")
    return _normalize_permission_node(permission)


def _normalize_permission_node(node: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            normalized[key] = _normalize_permission_node(value)
        elif isinstance(value, str):
            normalized[key] = _normalize_action(value)
        else:
            raise ValueError(
                f"valor inválido en permission[{key!r}]: debe ser string o objeto"
            )
    return normalized


def validate_opencode_permission(permission: dict[str, Any]) -> None:
    """Valida tipos y acciones. Raises ValueError si inválido."""
    if not isinstance(permission, dict):
        raise ValueError("permission debe ser un objeto JSON.")
    _validate_permission_node(permission, path="permission")


def _validate_permission_node(node: dict[str, Any], *, path: str) -> None:
    for key, value in node.items():
        current = f"{path}.{key}"
        if isinstance(value, dict):
            _validate_permission_node(value, path=current)
        elif isinstance(value, str):
            _normalize_action(value)
        else:
            raise ValueError(f"{current}: valor debe ser string (allow|ask|deny) u objeto")


def detect_unsupported_opencode_tools(permission: dict[str, Any]) -> list[str]:
    """Tools OpenCode no mapeadas en CI2Lab (warning, no error)."""
    unsupported: list[str] = []
    for key in permission:
        if key not in _SUPPORTED_OPENCODE_KEYS:
            unsupported.append(str(key))
    return sorted(unsupported)


def collect_permission_warnings(permission: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    unsupported = detect_unsupported_opencode_tools(permission)
    if unsupported:
        warnings.append(
            "Tools OpenCode no soportadas en CI2Lab (ignoradas): "
            + ", ".join(unsupported)
        )
    if _external_directory_allows(permission):
        warnings.append(_EXTERNAL_ALLOW_WARNING)
    return warnings


def _external_directory_allows(permission: dict[str, Any]) -> bool:
    ext = permission.get("external_directory")
    if isinstance(ext, str):
        return ext.strip().lower() == "allow"
    if isinstance(ext, dict):
        for pattern, action in ext.items():
            if str(action).strip().lower() == "allow":
                if pattern in ("*", "**"):
                    return True
        best = ext.get("*")
        return isinstance(best, str) and best.strip().lower() == "allow"
    return False


def load_opencode_config_bundle(
    path: str | Path,
    *,
    config_source: str | None = None,
) -> OpenCodeConfigBundle:
    """Carga, extrae, normaliza y valida permission desde archivo JSON."""
    raw_path = Path(path).expanduser().resolve()
    raw = load_opencode_config(raw_path)
    permission = extract_opencode_permission(raw)
    validate_opencode_permission(permission)
    normalized = normalize_opencode_permission(permission)
    unsupported = detect_unsupported_opencode_tools(permission)
    warnings = collect_permission_warnings(permission)
    return OpenCodeConfigBundle(
        config_source=config_source or str(raw_path),
        raw_config=raw,
        permission=permission,
        normalized_permission=normalized,
        unsupported_tools=unsupported,
        warnings=warnings,
    )


def bundle_from_permission(
    permission: dict[str, Any],
    *,
    config_source: str = "<inline>",
) -> OpenCodeConfigBundle:
    validate_opencode_permission(permission)
    normalized = normalize_opencode_permission(permission)
    unsupported = detect_unsupported_opencode_tools(permission)
    warnings = collect_permission_warnings(permission)
    return OpenCodeConfigBundle(
        config_source=config_source,
        raw_config={"permission": permission},
        permission=dict(permission),
        normalized_permission=normalized,
        unsupported_tools=unsupported,
        warnings=warnings,
    )


def bundle_from_preset(preset_name: str) -> OpenCodeConfigBundle:
    from ci2lab.security.opencode_presets import preset_permissions

    permission = preset_permissions(preset_name)
    bundle = bundle_from_permission(permission, config_source=f"preset:{preset_name}")
    return bundle


def export_opencode_format(permission: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_opencode_permission(permission)
    return {"permission": normalized}


def export_ci2lab_format(
    permission: dict[str, Any],
    *,
    permission_preset: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_opencode_permission(permission)
    security: dict[str, Any] = {
        "engine": "opencode_experimental",
        "permission": normalized,
    }
    if permission_preset:
        security["permission_preset"] = permission_preset
    return {"security": security}


def export_warnings_for_permission(permission: dict[str, Any]) -> list[str]:
    return collect_permission_warnings(permission)


def write_json_output(
    payload: dict[str, Any],
    *,
    output: Path | None,
    workspace: Path | None = None,
) -> None:
    """Escribe JSON a stdout o archivo (--output dentro de workspace si relativo)."""
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output is None:
        print(text, end="")
        return
    target = Path(output).expanduser()
    if not target.is_absolute() and workspace is not None:
        target = workspace.resolve() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
