# IAmultiagentica

CLI local que detecta las capacidades del ordenador, elige el modelo open source óptimo y ejecuta un agente con herramientas en terminal (VS Code, PowerShell, CMD).

## Estructura

Todo el código del producto está **aquí**. Los repos de referencia (claude-code, odysseus, opencode, deepagents) están en la carpeta padre `Ci2Lab/` y no forman parte de este paquete.

Ver [`docs/STRUCTURE.md`](docs/STRUCTURE.md).

## Módulos

| Módulo | Estado | Descripción |
|--------|--------|-------------|
| `ci2lab/contracts/` | ✅ | Contrato router ↔ arnés |
| `ci2lab/hardware/` | 🔲 | Perfilador RAM/VRAM/GPU |
| `ci2lab/router/` | 🔲 | Catálogo + selección de modelo |
| `ci2lab/runtime/` | 🔲 | Ollama pull/ensure |
| `ci2lab/harness/` | 🔲 | Arnés agéntico (ReAct + tools) |

## Instalación (desarrollo)

```bash
cd IAmultiagentica
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Documentación

- [Estructura del proyecto](docs/STRUCTURE.md)
- [Handoff: hardware + router](docs/HARDWARE_ROUTER_HANDOFF.md)
- [Repos externos de referencia](references/EXTERNAL_REPOS.md)

## Workspace

```text
Ci2Lab/
  IAmultiagentica/     ← este proyecto
  claude-code-main/    ← solo referencia
  odysseus-dev/
  opencode-dev/
  deepagents-main/
```
