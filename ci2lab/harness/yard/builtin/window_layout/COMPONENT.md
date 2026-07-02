---
name: window_layout
title: Multi-monitor two-window browser layout (cross-platform)
description: Detect connected screens, pick the primary in a multi-monitor setup, compute a 2/3 + 1/3 two-window layout, and (optionally) open and position two browser windows on macOS or Windows.
when_to_use: Launching a side-by-side two-pane browser layout on the primary display, or just computing the pixel bounds for such a layout.
kind: utility
tags: window-management, multi-monitor, screen-detection, cross-platform, layout, desktop-launcher
requires:
yard_id: yard-6e55ab6ec2
source_repo: Proyecto-Alvaro
signature: sha256:7ccc32f04f1f18f667dfaf3977922f49a4a7820af2072d493a16119d049382c1
core_sha256: sha256:bfcc923faa2d5fff6de2d26b0f52348e5fac37638765dfdf5174623281f10a4c
---

```json
{
  "entrypoints": [
    {
      "function": "calcular_layout_pantallas",
      "module": "launcher",
      "ready": "pure",
      "summary": "Compute the 2/3 (maps) + 1/3 (app) pixel bounds for the target screen; falls back to 1920x1080.",
      "parameters": {
        "type": "object",
        "properties": {
          "pantallas": {"type": "array", "description": "List of screen dicts {nombre, ancho, alto, es_principal}. Empty list → 1920x1080 fallback."}
        },
        "required": ["pantallas"]
      }
    },
    {
      "function": "elegir_pantalla_objetivo",
      "module": "launcher",
      "ready": "pure",
      "summary": "Pick the target screen: the primary one if flagged, else the first.",
      "parameters": {
        "type": "object",
        "properties": {
          "pantallas": {"type": "array", "description": "List of screen dicts."}
        },
        "required": ["pantallas"]
      }
    },
    {
      "function": "detectar_pantallas_macos",
      "module": "launcher",
      "ready": "pure",
      "summary": "Detect connected screens via macOS `system_profiler`; returns [] on non-macOS or on failure (never raises).",
      "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
      "function": "abrir_layout",
      "module": "launcher",
      "ready": "side_effect",
      "note": "Opens two real browser windows on the host and repositions them (AppleScript on macOS, Win32 MoveWindow via PowerShell on Windows). Re-run with args.confirm=true to proceed.",
      "summary": "Open and position the two-window layout for a Streamlit app on the given port.",
      "parameters": {
        "type": "object",
        "properties": {
          "puerto": {"type": "integer", "description": "Local port of the app window."},
          "confirm": {"type": "boolean", "description": "Must be true to actually open windows."}
        },
        "required": ["puerto"]
      }
    }
  ]
}
```

# Multi-monitor window layout

Pure, directly reusable: macOS screen detection (`system_profiler` parsing),
primary-screen selection, and the 2/3 + 1/3 layout computation. The
window-*opening* functions (macOS AppleScript, Windows Win32 `MoveWindow` via
PowerShell) are gated behind `confirm` because they act on the host.

**Porting guide.** The two module constants `STREAMLIT_HOST` and
`GOOGLE_MAPS_URL` were redacted in the salvaged source and are stubbed with
neutral defaults (`localhost`, the public Google Maps URL) so the launcher runs
standalone — turn them into parameters for real use. The 2/3 proportion is
hard-coded in `_layout_single_screen`; expose it as an argument if you need
other splits.
