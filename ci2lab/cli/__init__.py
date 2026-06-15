"""CLI de Ci2Lab. Punto de entrada: `ci2lab` → main()."""

from ci2lab.cli.commands.doctor import (
    _DOCTOR_ERROR,
    _DOCTOR_OK,
    _DOCTOR_WARN,
    _cmd_doctor,
    _missing_document_dependencies,
)
from ci2lab.cli.main import _expand_tools_shortcut, main
from ci2lab.cli.parser import _is_global_help_request, _print_global_help

__all__ = [
    "_DOCTOR_ERROR",
    "_DOCTOR_OK",
    "_DOCTOR_WARN",
    "_cmd_doctor",
    "_expand_tools_shortcut",
    "_is_global_help_request",
    "_missing_document_dependencies",
    "_print_global_help",
    "main",
]
