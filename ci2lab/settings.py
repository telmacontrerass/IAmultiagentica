"""
Permisos de herramientas via settings.json jerárquico.

Formato del archivo:
    {
      "allow": { "<tool>": ["<patron>", ...] },
      "deny":  { "<tool>": ["<patron>", ...] }
    }

Semántica:
  - deny evalúa primero y gana siempre (no son complementarios).
  - Si una tool no aparece en allow → permitida por defecto.
  - Si una tool aparece en allow → el sujeto debe coincidir al menos un patrón.
  - allow + deny en la misma tool → deny gana si hay coincidencia.

Jerarquía de archivos (orden de carga):
  1. ~/.ci2lab/settings.json  (global / usuario)
  2. .ci2lab/settings.json    (proyecto; se aplica encima del global)

Reglas de fusión:
  - deny:  acumulación. El proyecto no puede quitar denies del nivel global.
  - allow: el proyecto sobreescribe por tool (puede ampliar o restringir).
"""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_FILENAME = "settings.json"
_VALID_TOP_KEYS = frozenset({"allow", "deny"})


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------

@dataclass
class ToolSettings:
    """Reglas allow/deny ya fusionadas de todos los niveles activos."""

    allow: dict[str, list[str]] = field(default_factory=dict)
    deny: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ToolSettings:
        return cls()


# ---------------------------------------------------------------------------
# Rutas de búsqueda
# ---------------------------------------------------------------------------

def _settings_paths(cwd: str) -> list[Path]:
    """
    Devuelve las rutas donde buscar settings.json, de menor a mayor
    especificidad.  La última capa (proyecto) tiene más precedencia en allow.
    """
    return [
        Path.home() / ".ci2lab" / _SETTINGS_FILENAME,
        Path(cwd).resolve() / ".ci2lab" / _SETTINGS_FILENAME,
    ]


# ---------------------------------------------------------------------------
# Lectura y parseo de un archivo
# ---------------------------------------------------------------------------

def _load_raw(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning("settings.json: no se pudo leer %s: %s", path, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("settings.json: JSON inválido en %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("settings.json: %s no es un objeto JSON; ignorado.", path)
        return None
    return data


def _parse_tool_patterns(
    raw: Any,
    *,
    context: str,
) -> dict[str, list[str]]:
    """
    Parsea un bloque allow o deny.

    Acepta:
      { "bash": ["rm *", "del *"], "read_file": "*.env" }

    Ignora entradas inválidas con aviso en lugar de lanzar excepciones.
    """
    if not isinstance(raw, dict):
        logger.warning(
            "settings.json (%s): debe ser {tool: [patrones]}; ignorado.", context
        )
        return {}
    result: dict[str, list[str]] = {}
    for tool, patterns in raw.items():
        tool = str(tool)
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list):
            logger.warning(
                "settings.json (%s.%s): patrones deben ser lista o string; ignorado.",
                context,
                tool,
            )
            continue
        cleaned = [str(p).strip() for p in patterns if str(p).strip()]
        if cleaned:
            result[tool] = cleaned
    return result


def _parse_single_file(data: dict[str, Any], *, source: str) -> ToolSettings:
    unknown = set(data.keys()) - _VALID_TOP_KEYS
    if unknown:
        logger.warning(
            "settings.json (%s): claves desconocidas ignoradas: %s", source, unknown
        )
    allow = _parse_tool_patterns(
        data.get("allow", {}), context=f"{source}.allow"
    )
    deny = _parse_tool_patterns(
        data.get("deny", {}), context=f"{source}.deny"
    )
    return ToolSettings(allow=allow, deny=deny)


# ---------------------------------------------------------------------------
# Fusión de capas
# ---------------------------------------------------------------------------

def _merge(global_s: ToolSettings, project_s: ToolSettings) -> ToolSettings:
    """
    Fusiona capa global y capa de proyecto:

    deny  → unión. Los patrones del global NO pueden ser eliminados por
            el proyecto. El proyecto solo puede añadir más restricciones.
    allow → el proyecto sobreescribe por tool (puede ampliar o cambiar).
            Si una tool no aparece en el proyecto, se mantiene el global.
    """
    # deny: acumular sin duplicados, manteniendo orden
    merged_deny: dict[str, list[str]] = {}
    all_deny_tools = set(global_s.deny) | set(project_s.deny)
    for tool in all_deny_tools:
        seen: list[str] = []
        for p in global_s.deny.get(tool, []) + project_s.deny.get(tool, []):
            if p not in seen:
                seen.append(p)
        merged_deny[tool] = seen

    # allow: proyecto gana por tool; si el proyecto no define una tool,
    # se conserva el valor global
    merged_allow: dict[str, list[str]] = {**global_s.allow, **project_s.allow}

    return ToolSettings(allow=merged_allow, deny=merged_deny)


# ---------------------------------------------------------------------------
# Carga pública
# ---------------------------------------------------------------------------

def load_settings(cwd: str) -> ToolSettings:
    """
    Carga y fusiona settings.json de nivel global y de proyecto.

    Nunca lanza excepciones; errores de lectura o parseo se registran
    con logging.warning y se ignoran silenciosamente.
    """
    layers: list[ToolSettings] = []
    for path in _settings_paths(cwd):
        raw = _load_raw(path)
        if raw is not None:
            layers.append(_parse_single_file(raw, source=str(path)))

    if not layers:
        return ToolSettings.empty()
    if len(layers) == 1:
        return layers[0]
    return _merge(layers[0], layers[1])


# ---------------------------------------------------------------------------
# Evaluación de una llamada concreta
# ---------------------------------------------------------------------------

def subject_for_tool(tool_name: str, args: dict[str, Any]) -> str:
    """
    Extrae el 'sujeto' relevante de una llamada para compararlo con patrones.

    | Tool        | Sujeto                         |
    |-------------|--------------------------------|
    | bash        | el comando completo            |
    | web_fetch   | la URL                         |
    | *_file / ls / glob / grep / tree / inspect_file | la ruta |
    | resto       | "*" (siempre coincide con "*") |
    """
    if tool_name == "bash":
        return str(args.get("command", ""))
    if tool_name == "web_fetch":
        return str(args.get("url", ""))
    if tool_name == "fill_docx_template":
        # El sujeto es la ruta de salida (el archivo que se va a escribir).
        # La ruta de la plantilla se valida por workspace containment en preview_fill_docx.
        return str(args.get("output", "*"))
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    return "*"


def _normalize_path(s: str) -> str:
    """Normaliza separadores para comparación cross-platform."""
    return s.replace("\\", "/")


def _pattern_matches(pattern: str, subject: str) -> bool:
    """
    Compara un patrón glob contra el sujeto.

    Estrategias (por orden):
    1. fnmatch directo (case-insensitive en Windows).
    2. Prefix match para comandos bash con espacios (ej: "rm *" cubre "rm -rf .").
    3. Para patrones con "**": PurePosixPath.full_match() (Python 3.13+).
       - "**" puede representar cero o más segmentos de directorio.
       - Respeta prefijos concretos: ".ci2lab/output/**/*.docx" NO coincide con
         "otro/malicioso.docx".
       - Fallback para Python < 3.13: bare-filename solo cuando el patrón
         empieza con "**/" sin prefijo concreto.
    4. Para patrones sin "**": coincidencia contra el nombre de archivo desnudo
       (ej: "*.pdf" coincide con "docs/informe.pdf").
    """
    norm_s = _normalize_path(subject)
    norm_p = _normalize_path(pattern)

    # coincidencia directa (case-insensitive en Windows vía lower())
    if fnmatch.fnmatchcase(norm_s, norm_p) or fnmatch.fnmatchcase(
        norm_s.lower(), norm_p.lower()
    ):
        return True

    # para bash: intentar prefix match (rm * debe cubrir "rm -rf .")
    if " " in norm_p and norm_s.startswith(norm_p.split("*")[0]):
        return True

    # para patrones con **: usar PurePosixPath.full_match() (Python 3.13+).
    # Path.match() dejó de soportar ** en Python 3.13; full_match() es el
    # reemplazo oficial y maneja correctamente cero segmentos y prefijos concretos.
    if "**" in norm_p:
        from pathlib import PurePosixPath

        if "/**/" in norm_p:
            zero_segment_pattern = norm_p.replace("/**/", "/")
            if fnmatch.fnmatchcase(norm_s, zero_segment_pattern) or fnmatch.fnmatchcase(
                norm_s.lower(), zero_segment_pattern.lower()
            ):
                return True

        try:
            if PurePosixPath(norm_s).full_match(norm_p):
                return True
            # case-insensitive (Windows)
            if PurePosixPath(norm_s.lower()).full_match(norm_p.lower()):
                return True
        except AttributeError:
            # Python < 3.13: full_match no disponible; fallback manual.
            # Solo aplicamos bare-filename cuando el patrón empieza con "**/"
            # (sin prefijo concreto) para no ignorar el prefijo por error.
            if norm_p.startswith("**/"):
                suffix = norm_p[3:]
                if suffix:
                    bare = norm_s.rsplit("/", 1)[-1] if "/" in norm_s else norm_s
                    if fnmatch.fnmatchcase(bare, suffix) or fnmatch.fnmatchcase(
                        bare.lower(), suffix.lower()
                    ):
                        return True

    # coincidencia solo contra el nombre de archivo (último segmento)
    # para patrones sin ** usados contra rutas con directorio (ej: "*.pdf" vs "docs/x.pdf")
    filename = norm_s.rsplit("/", 1)[-1]
    if filename and filename != norm_s:
        if fnmatch.fnmatchcase(filename, norm_p) or fnmatch.fnmatchcase(
            filename.lower(), norm_p.lower()
        ):
            return True

    return False


def _first_match(patterns: list[str], subject: str) -> str | None:
    """Devuelve el primer patrón que coincide, o None."""
    for p in patterns:
        if _pattern_matches(p, subject):
            return p
    return None


def check_tool_allowed(
    settings: ToolSettings,
    tool_name: str,
    args: dict[str, Any],
) -> tuple[bool, str]:
    """
    Evalúa si una tool call está permitida según las reglas de settings.json.

    Devuelve (allowed: bool, reason: str).

    Algoritmo:
      1. Extraer el sujeto (ruta, comando, URL, o "*").
      2. Buscar en deny[tool_name]: si hay coincidencia → bloqueado (deny gana).
      3. Si allow[tool_name] existe: el sujeto debe coincidir al menos un patrón.
      4. Si allow[tool_name] no existe: permitido por defecto.
    """
    subject = subject_for_tool(tool_name, args)

    # 1. Deny: evalúa primero, gana siempre
    deny_patterns = settings.deny.get(tool_name, [])
    matched_deny = _first_match(deny_patterns, subject)
    if matched_deny:
        return (
            False,
            f"bloqueado por settings.json deny[{tool_name!r}] patron={matched_deny!r}",
        )

    # 2. Allow: si hay lista y el sujeto no coincide → bloqueado
    allow_patterns = settings.allow.get(tool_name)
    if allow_patterns is not None:
        matched_allow = _first_match(allow_patterns, subject)
        if matched_allow is None:
            return (
                False,
                f"bloqueado por settings.json allow[{tool_name!r}]: "
                f"ningún patrón coincide con {subject!r}",
            )

    # 3. Permitido
    return True, "settings:allowed"
