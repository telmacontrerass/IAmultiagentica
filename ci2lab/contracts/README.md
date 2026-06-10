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

El router está implementado y expuesto vía CLI (`ci2lab hardware`, `ci2lab models …`), pero `pipeline.prepare_session()` aún no lo conecta al flujo `chat`/`agent`. Ver [`docs/KNOWN_LIMITATIONS.md`](../../docs/KNOWN_LIMITATIONS.md).

## Documentación completa

Ver [`docs/HARDWARE_ROUTER_HANDOFF.md`](../../docs/HARDWARE_ROUTER_HANDOFF.md).
