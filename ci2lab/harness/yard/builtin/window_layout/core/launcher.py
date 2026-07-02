import json
import platform
import re
import subprocess
import time
import webbrowser

# Elided in the salvaged artifact (business-specific); neutral defaults
# so the launcher entrypoints run standalone.
STREAMLIT_HOST = "localhost"
GOOGLE_MAPS_URL = "https://www.google.com/maps"


def detectar_pantallas_macos():
    """Detecta las pantallas conectadas en macOS vía `system_profiler`.

    Returns:
        Lista de dicts con las pantallas detectadas. Cada dict tiene:
          - nombre (str): nombre legible de la pantalla.
          - ancho (int): ancho en píxeles lógicos.
          - alto (int): alto en píxeles lógicos.
          - es_principal (bool): True si es la pantalla principal (con
            barra de menú).
        Si el comando falla o no se puede parsear, devuelve `[]`. La función
        nunca propaga excepciones para no romper el launcher.
    """
    try:
        salida = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        data = json.loads(salida)
    except Exception:
        return []

    pantallas = []
    # La estructura es: SPDisplaysDataType -> [GPU] -> spdisplays_ndrvs -> [pantalla]
    for gpu in data.get("SPDisplaysDataType", []) or []:
        for display in gpu.get("spdisplays_ndrvs", []) or []:
            # Probar varios campos hasta encontrar uno parseable con WxH.
            ancho_alto = None
            for campo in ("_spdisplays_resolution",
                          "spdisplays_pixelresolution",
                          "_spdisplays_pixels"):
                valor = display.get(campo)
                if not valor or not isinstance(valor, str):
                    continue
                m = re.search(r"(\d+)\s*x\s*(\d+)", valor)
                if m:
                    ancho_alto = (int(m.group(1)), int(m.group(2)))
                    break
            if ancho_alto is None:
                continue
            pantallas.append({
                "nombre": display.get("_name", "Display"),
                "ancho": ancho_alto[0],
                "alto": ancho_alto[1],
                "es_principal":
                    display.get("spdisplays_main") == "spdisplays_yes",
            })
    return pantallas


# ... [omitido: helper de eleccion de pantalla principal, docstring elidido por D11] ...
def elegir_pantalla_objetivo(pantallas):
    # ... [omitido: docstring con referencia al proyecto origen] ...
    if not pantallas:
        return None
    if len(pantallas) == 1:
        return pantallas[0]
    for p in pantallas:
        if p.get("es_principal"):
            return p
    return pantallas[0]


def _layout_single_screen(sw, sh):
    # ... [omitido: docstring con referencias de negocio del proyecto origen] ...
    maps_width = int(sw * 2 / 3)
    return {
        "maps_bounds": (0, 0, maps_width, sh),
        "app_bounds": (maps_width, 0, sw, sh),
    }


def calcular_layout_pantallas(pantallas):
    # ... [omitido: docstring con referencias de negocio del proyecto origen] ...
    objetivo = elegir_pantalla_objetivo(pantallas)
    if objetivo is None:
        # Fallback razonable: full HD primario.
        return _layout_single_screen(1920, 1080)
    return _layout_single_screen(objetivo["ancho"], objetivo["alto"])


# ... [omitido: nada esencial entre helpers] ...

def abrir_ventanas_macos(url_maps, url_app):
    """Abre dos ventanas de Safari posicionadas: 2/3 izquierda + 1/3 derecha
    en la pantalla primaria.

    Detecta la configuración de pantallas con system_profiler y calcula el
    layout en Python. Esto evita el bug de multi-monitor donde
    `bounds of window of desktop` devolvía el escritorio virtual completo.
    """
    pantallas = detectar_pantallas_macos()
    layout = calcular_layout_pantallas(pantallas)
    mx1, my1, mx2, my2 = layout["maps_bounds"]
    ax1, ay1, ax2, ay2 = layout["app_bounds"]

    applescript = f'''
    tell application "Safari"
        activate
        make new document with properties {{URL:"{url_maps}"}}
        delay 0.5
        make new document with properties {{URL:"{url_app}"}}
        delay 0.5
    end tell

    tell application "Safari"
        set bounds of window 1 to {{{ax1}, {ay1}, {ax2}, {ay2}}}
        set bounds of window 2 to {{{mx1}, {my1}, {mx2}, {my2}}}
    end tell
    '''
    subprocess.Popen(["osascript", "-e", applescript])


# ... [omitido: nada esencial entre helpers] ...

def abrir_ventanas_windows(url_maps, url_app):
    """Abre dos ventanas del navegador por defecto y las posiciona con PowerShell."""
    webbrowser.open(url_maps)
    time.sleep(1.5)
    webbrowser.open(url_app)
    time.sleep(1.5)

    # Best-effort: posicionar ventanas via PowerShell
    ps_script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int W, int H, bool repaint);
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$sw = $screen.Width
$sh = $screen.Height
$mapsW = [int]($sw * 2 / 3)
# Las dos ventanas mas recientes del navegador
$procs = Get-Process | Where-Object {$_.MainWindowHandle -ne 0 -and ($_.ProcessName -match "chrome|msedge|firefox|brave")} | Sort-Object StartTime -Descending | Select-Object -First 2
if ($procs.Count -ge 2) {
    # La mas reciente es la app (abierta segunda), la otra es Maps
    [Win32]::MoveWindow($procs[0].MainWindowHandle, $mapsW, 0, ($sw - $mapsW), $sh, $true)
    [Win32]::MoveWindow($procs[1].MainWindowHandle, 0, 0, $mapsW, $sh, $true)
}
'''
    try:
        subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, timeout=10
        )
    except Exception:
        pass  # Best-effort: si falla, las ventanas quedan donde estén


# ... [omitido: nada esencial entre helpers] ...

def abrir_layout(puerto):
    url_app = f"http://{STREAMLIT_HOST}:{puerto}"
    url_maps = GOOGLE_MAPS_URL

    sistema = platform.system()
    if sistema == "Darwin":
        abrir_ventanas_macos(url_maps, url_app)
    elif sistema == "Windows":
        abrir_ventanas_windows(url_maps, url_app)
    else:
        webbrowser.open(url_maps)
        webbrowser.open(url_app)