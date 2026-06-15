# Limitaciones conocidas — Ci2Lab

Última revisión: 2026-06-12.

## Integración pipeline ↔ router

| Limitación | Detalle |
|------------|---------|
| Router no auto-selecciona modelo en chat | `ci2lab models recommend` sugiere; el usuario elige con `--model`. |
| `tool_mode` desde catálogo | `prepare_session()` + `build_model_selection()` aplican el modo del catálogo; override con `--tool-mode` o yaml. |
| Tags no catalogados | Modelos desconocidos usan `tool_mode: fenced` por defecto. |
| Sin auto-pull | `runtime/ensure.py` no existe; el usuario debe hacer `ollama pull`. |
| `ci2lab agent --session` sin historial | `--session` guarda pero no carga mensajes previos (sí `chat --session` y la UI). |
| `resolve_model()` sin uso en producción | API opcional; chat/agent/UI usan `build_model_selection()`. |

## Fuera de alcance (aún)

| Área | Estado |
|------|--------|
| Runtime automático (`ollama pull` / ensure) | No implementado |
| Git snapshot / rollback / auto-commit | No implementado |
| Routing multi-modelo por turno | No implementado |
| Benchmark live por modelo del catálogo | Solo scores estáticos en `models.json` |
| Memoria vectorial entre sesiones | No implementado |
| Hooks extensibles tipo Claude Code | No implementado |

## Integrado

| Área | Estado |
|------|--------|
| MCP cliente (stdio) | ✅ `.ci2lab/mcp.json` |
| Skills workspace | ✅ `.ci2lab/skills/*/SKILL.md` |
| Project memory | ✅ `CI2LAB.md`, `AGENTS.md` |
| UI web local | ✅ `ci2lab ui` |
| Compactación de contexto | ✅ `harness/context/` |
| Motores de seguridad | ✅ `ci2lab/security/` (`ci2lab`, `claude_experimental`, …) |
| 22 herramientas built-in | ✅ `harness/tools/schemas.py` |

## Seguridad y sandbox

Ver [`SECURITY_POLICY.md`](SECURITY_POLICY.md).

| Limitación | Detalle |
|------------|---------|
| Sin sandbox OS/contenedor | Confirmación + blocklist; no seccomp ni red aislada |
| Rutas | `resolve_path()` confina al workspace |
| Archivos sensibles | Heurística en `secret_files`; no clasificador perfecto |
| `bash` con `shell=True` | `--yes` no omite blocklist de workspace |

## Operación del harness

| Limitación | Detalle |
|------------|---------|
| Parser heterogéneo | Modelos locales pueden imprimir tools como texto |
| Compactación | Historial antiguo se resume o recorta |
| Trim grosero | ~4 caracteres/token |
| REPL / sesiones | `~/.ci2lab/sessions/`; reanudar con `chat --session ID` |
| CLI flags | Flags del agente van **antes** del subcomando |
| Entrada terminal | `prompt_toolkit` en REPL/ask_user; confirmaciones usan `input()` |

## Tests

Ejecutar `python -m pytest -q` (560+ tests). Cubre harness, tools, MCP, skills, router, CLI y security.
