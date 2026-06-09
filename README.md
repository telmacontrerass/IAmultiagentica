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
| `ci2lab/harness/` | ✅ | Arnés completo (ReAct, 7 tools, REPL, sesiones, streaming) |

## Instalación para usarlo

Requisitos:

- Python 3.11 o superior.
- [Ollama](https://ollama.com/download) instalado y abierto.

### macOS / Linux

```bash
cd IAmultiagentica
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ci2lab doctor
ci2lab models recommend
ci2lab models install qwen2.5-coder-1.5b
ollama pull qwen2.5-coder:1.5b
ci2lab models run qwen2.5-coder-1.5b
```

### Windows PowerShell

```powershell
cd IAmultiagentica
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ci2lab doctor
ci2lab models recommend
ci2lab models install qwen2.5-coder-1.5b
ollama pull qwen2.5-coder:1.5b
ci2lab models run qwen2.5-coder-1.5b
```

`ci2lab models recommend` muestra los modelos permitidos para ese ordenador. El usuario puede pasar a `install` el ID del catálogo (`qwen2.5-coder-1.5b`) o el tag de Ollama (`qwen2.5-coder:1.5b`).

Comandos útiles:

```bash
ci2lab chat                              # modo interactivo agéntico
ci2lab sessions                          # historial guardado
ci2lab "lista los archivos Python" --model qwen2.5-coder-1.5b --yes
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
