# Handoff: Perfilador de hardware + Router de modelos

> **Para la IA / desarrollador que implementa esta parte.**  
> El arnés agéntico lo implementa otra persona. Este documento define **qué construir**, **qué no tocar** y **cómo encajar con el arnés** al final.

**Raíz del proyecto:** `Ci2Lab/IAmultiagentica/`  
**Workspace padre:** `Ci2Lab/` (solo repos de referencia, ver `references/EXTERNAL_REPOS.md`)

---

## 1. Contexto del proyecto

**IAmultiagentica** (paquete Python `ci2lab`) es una CLI local que:

1. Detecta las capacidades del ordenador (RAM, VRAM, GPU).
2. Interpreta la intención del usuario (ej. `"programar muy bien"`).
3. Elige el mejor modelo open source que **quepa** en ese hardware.
4. (Opcional) Descarga/arranca el modelo vía Ollama.
5. Pasa el control al **arnés agéntico**, que ejecuta el bucle ReAct con herramientas.

```
┌─────────────────────────────────────────────────────────────┐
│  TU PARTE (este handoff)                                    │
│  hardware/  +  router/  +  runtime/ (ensure_model)          │
└───────────────────────────┬─────────────────────────────────┘
                            │  ModelSelection (contrato)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  PARTE DEL COMPAÑERO (arnés)                                │
│  harness/  — bucle ReAct, tools, prompts, permisos          │
└─────────────────────────────────────────────────────────────┘
```

**Regla de oro:** no importar opencode, deepagents, odysseus ni claude-code como dependencias. Solo consultar los repos en `../` (ver `references/EXTERNAL_REPOS.md`) y anotar extracciones en `references/EXTRACTION_LOG.md`.

---

## 2. Alcance: qué SÍ y qué NO

### ✅ Tu responsabilidad

| Módulo | Descripción |
|--------|-------------|
| `IAmultiagentica/ci2lab/hardware/` | Escanear RAM, VRAM, GPU, OS, modo inferencia (CPU/GPU) |
| `IAmultiagentica/ci2lab/router/` | Catálogo de modelos, clasificación de intención, selección óptima |
| `IAmultiagentica/ci2lab/runtime/` | Comprobar/descargar/arrancar modelo en Ollama (MVP) |
| `IAmultiagentica/ci2lab/catalog/` | JSON/YAML con modelos reales (Mistral, Qwen, Llama, Gemma, NVIDIA) |
| CLI | `ci2lab hardware`, `ci2lab models recommend`, `ci2lab models pull` |
| Tests | `IAmultiagentica/tests/` — profiler, selector, casos límite de VRAM |

### ❌ Fuera de tu alcance (arnés)

- Bucle ReAct, parsing de tool calls, ejecución de bash/read/grep
- System prompts del agente, permisos de herramientas
- `ci2lab/harness/` (excepto **consumir** `ModelSelection`)

### 🤝 Contrato compartido (NO modificar sin acuerdo)

Archivo: **`IAmultiagentica/ci2lab/contracts/types.py`**

Ambas partes importan solo de ahí para integrarse. Si necesitas un campo nuevo, añádelo con valor opcional y documenta en este archivo.

---

## 3. Contrato de integración (lo más importante)

### 3.1 Entrada que recibes del usuario

```python
user_prompt: str          # ej. "programar muy bien"
cwd: str | None = None    # directorio de trabajo (opcional)
force_model: str | None   # override manual (--model)
```

### 3.2 Salida que debes producir: `ModelSelection`

El arnés llamará:

```python
from ci2lab.contracts.types import ModelSelection, HardwareProfile

selection: ModelSelection = resolve_model(user_prompt, profile=profile)
# El arnés usa:
#   selection.ollama_tag      → modelo a cargar
#   selection.backend_url     → http://localhost:11434/v1
#   selection.tool_mode       → "native" | "fenced"
#   selection.context_length  → para trim de contexto
```

**Campos obligatorios de `ModelSelection`:** ver `ci2lab/contracts/types.py`.

### 3.3 Función pública que debes exponer

Implementar en `ci2lab/router/resolve.py`:

```python
def resolve_model(
    user_prompt: str,
    *,
    profile: HardwareProfile | None = None,
    force_model_id: str | None = None,
    prefer_installed: bool = True,
) -> ModelSelection:
    """
    1. profile = profile or scan_hardware()
    2. intent = classify_intent(user_prompt)
    3. model = select_best_model(intent, profile, force_model_id)
    4. return ModelSelection con metadatos para el arnés
    """
```

### 3.4 Función de arranque (runtime)

Implementar en `ci2lab/runtime/ensure.py`:

```python
def ensure_model_ready(selection: ModelSelection, *, pull: bool = True) -> None:
    """
    - Comprueba si Ollama tiene el tag
    - Si pull=True y no está → ollama pull
    - Opcional: warmup con prompt mínimo
    - Lanza RuntimeError claro si Ollama no responde
    """
```

### 3.5 Pipeline unificado (para CLI final)

En `ci2lab/pipeline.py` (puedes crearlo tú; el arnés lo reutilizará):

```python
def prepare_session(user_prompt: str, **kwargs) -> tuple[HardwareProfile, ModelSelection]:
    profile = scan_hardware()
    selection = resolve_model(user_prompt, profile=profile, **kwargs)
    ensure_model_ready(selection)
    return profile, selection
```

El compañero del arnés hará:

```python
profile, selection = prepare_session("programar muy bien")
await harness.run(user_prompt, selection=selection, profile=profile)
```

---

## 4. Estructura de carpetas

Todo dentro de **`IAmultiagentica/`**:

```text
IAmultiagentica/
├── pyproject.toml              # pip install -e .
├── README.md
├── docs/
│   ├── STRUCTURE.md
│   └── HARDWARE_ROUTER_HANDOFF.md
├── references/                 # Notas (no código de terceros)
├── tests/
└── ci2lab/                     # Paquete Python
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── pipeline.py
    ├── contracts/              # ⚠️ COMPARTIDO con arnés
    ├── hardware/
    ├── router/
    ├── runtime/
    ├── catalog/
    ├── harness/                # Lo implementa el compañero
    └── config/
```

Los repos de referencia están **fuera**, en `Ci2Lab/claude-code-main/`, etc.

**No crear** lógica de arnés en `router/` ni `hardware/`.

---

## 5. Hardware profiler

### 5.1 `HardwareProfile` (ya definido en contracts)

Debe rellenarse en cada `scan_hardware()` (con caché TTL 60s opcional).

### 5.2 Qué detectar

| Campo | Windows | Linux | Notas |
|-------|---------|-------|-------|
| `ram_total_gb` | `psutil` | `psutil` | |
| `ram_available_gb` | `psutil` | `psutil` | |
| `vram_total_gb` | `nvidia-smi` | `nvidia-smi` | 0 si solo CPU |
| `vram_available_gb` | `nvidia-smi` | `nvidia-smi` | estimar libre |
| `gpu_name` | nvidia-smi / WMI | nvidia-smi | `"CPU only"` si no hay GPU |
| `gpu_vendor` | `nvidia` \| `amd` \| `intel` \| `none` | idem | |
| `cpu_cores` | `psutil` | `psutil` | |
| `os` | `windows` \| `linux` \| `darwin` | | |
| `inference_mode` | `gpu` si VRAM≥4GB else `cpu` | idem | |
| `inference_budget_gb` | ver fórmula abajo | | |

### 5.3 Fórmula `inference_budget_gb`

```text
Si inference_mode == "gpu":
    inference_budget_gb = max(0, vram_available_gb - 2.0)
Si inference_mode == "cpu":
    inference_budget_gb = max(0, ram_available_gb * 0.6)
```

### 5.4 Comando CLI

```bash
cd IAmultiagentica
ci2lab hardware
ci2lab hardware --json
```

### 5.5 Criterios de aceptación

- [ ] En Windows del equipo objetivo devuelve RAM coherente (±1 GB).
- [ ] Si hay NVIDIA, reporta VRAM; si no, `inference_mode=cpu` sin crash.
- [ ] `ci2lab hardware --json` parseable por `json.loads`.

---

## 6. Catálogo de modelos

### 6.1 Fuente de datos

Convertir la tabla del proyecto a **`ci2lab/catalog/models.json`**.

Cada entrada:

```json
{
  "id": "qwen2.5-coder-32b",
  "display_name": "Qwen2.5 Coder 32B",
  "family": "qwen",
  "categories": ["coding", "refactor", "analysis"],
  "params_b": 32,
  "active_params_b": 32,
  "vram_inference_gb": 22,
  "ram_inference_gb": 24,
  "vram_min_gb": 20,
  "ollama_tag": "qwen2.5-coder:32b",
  "hf_repo": "Qwen/Qwen2.5-Coder-32B-Instruct",
  "supports_tools": true,
  "tool_mode": "native",
  "context_length": 32768,
  "tier": "workstation",
  "benchmark_score": {
    "coding": 0.92,
    "rag": 0.55,
    "reasoning": 0.70,
    "edge": 0.10
  }
}
```

### 6.2 `benchmarks.json`

Mejores modelos por categoría y tier (`edge`, `workstation`, `enterprise`). Los `id` deben existir en `models.json`.

### 6.3 Prioridad MVP del catálogo

| id | ollama_tag | categoría principal |
|----|------------|---------------------|
| qwen2.5-1.5b | qwen2.5:1.5b | edge |
| qwen2.5-7b | qwen2.5:7b | general |
| qwen2.5-coder-7b | qwen2.5-coder:7b | coding |
| qwen2.5-coder-32b | qwen2.5-coder:32b | coding |
| llama3.1-8b | llama3.1:8b | general |
| llama3.3-70b | llama3.3 | reasoning |
| codegemma-7b | codegemma:7b | coding |
| mistral-3-3b-instruct | mistral:3b | edge |

---

## 7. Clasificación de intención

### 7.1 Categorías

`coding`, `rag`, `reasoning`, `translation`, `vision`, `voice`, `edge`, `general`

### 7.2 MVP: reglas por keywords (sin LLM)

Implementar en `router/intent.py`.

### 7.3 Fase 2 (opcional)

Patrones tipo keyword/intent/capability router; implementar en `ci2lab/router/` sin dependencias externas.

---

## 8. Algoritmo de selección

Ver secciones 8.1–8.4 del plan original (tiers edge/workstation/enterprise, filtro por VRAM/RAM, fallback de tier, orden por `benchmark_score`).

---

## 9. Runtime Ollama (MVP)

- API: `http://localhost:11434`
- OpenAI-compatible: `http://localhost:11434/v1`
- Config: `~/.ci2lab/config.toml`

---

## 10. CLI

```bash
ci2lab doctor
ci2lab hardware [--json]
ci2lab models list [--category coding] [--fits]
ci2lab models show <id>
ci2lab models recommend "<prompt>" [--json]
ci2lab models pull <id|tag>
ci2lab prepare "<prompt>"
```

---

## 11. Configuración global

`~/.ci2lab/config.toml` — ver plan original.

---

## 12. Tests

Ubicación: **`IAmultiagentica/tests/`**

Casos mínimos: 6 GB VRAM, 24 GB VRAM, CPU 32 GB RAM, 4 GB VRAM + reasoning.

---

## 13. Material de referencia (fuera del proyecto)

Repos en `Ci2Lab/` (carpeta **padre** de `IAmultiagentica/`):

| Ruta | Uso |
|------|-----|
| `../claude-code-main/` | Prompts y descripciones de herramientas |
| `../odysseus-dev/` | agent_loop, tool_parsing, schemas |
| `../opencode-dev/` | Tool registry, permisos |
| `../deepagents-main/` | BASE_AGENT_PROMPT, filesystem middleware |
| Tabla de modelos del proyecto | Fuente de `catalog/models.json` |
| Benchmarks del proyecto | Fuente de `catalog/benchmarks.json` |

**No** copiar estos repos dentro de `IAmultiagentica/`. **No** importarlos como paquetes.

---

## 14. Integración final con el arnés

```python
from ci2lab.pipeline import prepare_session
from ci2lab.harness.loop import run_agent

profile, selection = prepare_session(prompt)
await run_agent(user_prompt=prompt, selection=selection, hardware=profile)
```

| Campo | Uso en arnés |
|-------|----------------|
| `selection.ollama_tag` | Modelo en API |
| `selection.backend_url` | Base URL OpenAI-compatible |
| `selection.tool_mode` | `native` vs `fenced` |
| `selection.context_length` | Recorte de historial |

---

## 15. Orden de implementación

1. `ci2lab/contracts/types.py` — **ya existe**
2. `catalog/models.json` + `benchmarks.json`
3. `hardware/profiler.py`
4. `router/intent.py` + `router/selector.py` + `router/resolve.py`
5. `runtime/ollama.py` + `ensure_model_ready`
6. `pipeline.py` + CLI
7. Tests

**Hito:** `ci2lab prepare "programar muy bien" --json` desde `IAmultiagentica/`.

---

## 16. Definición de terminado

- [ ] Trabajar siempre desde `IAmultiagentica/` (`pip install -e .`)
- [ ] `ci2lab hardware` funciona en Windows
- [ ] Catálogo ≥10 modelos + `benchmarks.json`
- [ ] `resolve_model()` → `ModelSelection` estable
- [ ] `ensure_model_ready()` con Ollama
- [ ] Tests con mocks (sin GPU real)
- [ ] `ci2lab prepare --json` consumible por el arnés

---

## 17. Preguntas frecuentes

**¿Dónde clono / desarrollo?** `cd Ci2Lab/IAmultiagentica`

**¿Python?** 3.11+

**¿pyproject.toml?** En la raíz de `IAmultiagentica/`

**¿Repos de referencia?** Hermanos en `Ci2Lab/`, no dentro del proyecto

---

*Última actualización: 2026-06-09. Contrato: `IAmultiagentica/ci2lab/contracts/types.py`.*
