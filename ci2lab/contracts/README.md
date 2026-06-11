# Contrato de integración

Este paquete define los tipos compartidos entre:

- **Router** (`ci2lab/hardware`, `ci2lab/router`, `ci2lab/runtime`) — perfil de hardware y selección de modelo
- **Arnés** (`ci2lab/harness`) — bucle agéntico

## Tipos principales

| Tipo | Productor | Consumidor | Uso |
|------|-----------|------------|-----|
| `HardwareProfile` | `hardware.scan_hardware()` | `router`, CLI | RAM/VRAM/GPU, presupuesto inferencia |
| `ModelSpec` | `catalog/models.json` | `router` | Metadatos de un modelo del catálogo |
| `ModelSelection` | `router.resolve_model()` | `harness` | Modelo elegido + tool_mode + context_length |
| `IntentResult` | `router.classify_intent()` | `router`, CLI | Categoría de intención del prompt |

## Reglas

1. Cualquier cambio en `types.py` debe ser retrocompatible (campos nuevos opcionales).
2. El router **produce** `HardwareProfile` y `ModelSelection`.
3. El arnés **consume** `ModelSelection` (y opcionalmente `HardwareProfile`).

## Estado de integración

- **Sugerencias:** `ci2lab models recommend` (router) — el usuario decide qué modelo ejecutar.
- **Ejecución:** `pipeline.prepare_session()` aplica el `tool_mode` del catálogo para el modelo elegido (`--model` / config).

## Documentación completa

Ver [`docs/HARDWARE_ROUTER_HANDOFF.md`](../../docs/HARDWARE_ROUTER_HANDOFF.md).
