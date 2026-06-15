# Contrato de integración

Este paquete define los tipos compartidos entre:

- **Router** (`ci2lab/hardware`, `ci2lab/router`, `ci2lab/runtime`) — perfil de hardware y metadatos de modelo
- **Arnés** (`ci2lab/harness`) — bucle agéntico ReAct
- **Pipeline** (`ci2lab/pipeline.py`) — une config de usuario, router y arnés

## Tipos principales

| Tipo | Productor | Consumidor | Uso |
|------|-----------|------------|-----|
| `HardwareProfile` | `hardware.scan_hardware()` | `router`, CLI, UI | RAM/VRAM/GPU, presupuesto inferencia |
| `ModelSpec` | `catalog/models.json` | `router` | Metadatos de un modelo del catálogo |
| `ModelSelection` | `router.selection.build_model_selection()` | `harness`, `pipeline` | Modelo elegido + tool_mode + context_length |
| `IntentResult` | `router.classify_intent()` | `router`, CLI | Categoría de intención del prompt |

`router.resolve_model()` existe como API opcional (auto-elige el primer recomendado); **no** usa el flujo de producción de `chat`/`agent`/UI.

## Reglas

1. Cualquier cambio en `types.py` debe ser retrocompatible (campos nuevos opcionales).
2. El router **produce** perfiles y metadatos; el usuario **elige** el modelo a ejecutar.
3. El arnés **consume** `ModelSelection` vía `AgentConfig` (construido en `pipeline.build_agent_config()`).

## Estado de integración

- **Sugerencias:** `ci2lab models recommend` — el usuario decide qué modelo ejecutar.
- **Ejecución:** `pipeline.prepare_session()` + `build_agent_config()` para CLI, UI y scripts.

## Documentación completa

Ver [`docs/HARDWARE_ROUTER_HANDOFF.md`](../../docs/HARDWARE_ROUTER_HANDOFF.md).
