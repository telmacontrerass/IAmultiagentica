# Contrato de integración

Este paquete define los tipos compartidos entre:

- **Router** (`ci2lab/hardware`, `ci2lab/router`, `ci2lab/runtime`) — perfil de hardware y selección de modelo
- **Arnés** (`ci2lab/harness`) — bucle agéntico

## Reglas

1. Cualquier cambio en `types.py` debe ser retrocompatible (campos nuevos opcionales).
2. El router **produce** `HardwareProfile` y `ModelSelection`.
3. El arnés **consume** `ModelSelection` (y opcionalmente `HardwareProfile`).

## Documentación completa

Ver [`docs/HARDWARE_ROUTER_HANDOFF.md`](../docs/HARDWARE_ROUTER_HANDOFF.md).
