#!/usr/bin/env bash
# instalar.sh — Instalador automático de ci2lab para macOS y Ubuntu/Linux
# Uso: bash instalar.sh
set -euo pipefail

# ── Colores ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✔  $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
err()  { echo -e "${RED}  ✖  $*${RESET}"; }
info() { echo -e "${CYAN}  ➜  $*${RESET}"; }
step() { echo -e "\n${BOLD}[ $* ]${RESET}"; }
ask()  {
    local msg="$1"
    echo -e "${YELLOW}  ?  ${msg} [s/N] ${RESET}"
    read -r resp
    [[ "$resp" =~ ^[sS]$ ]]
}

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=11

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       Instalador de ci2lab               ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""
info "Directorio del proyecto: $REPO_DIR"

# ── Paso 1: Python ─────────────────────────────────────────────────────────────
step "1/5 · Comprobando Python"

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR="${VER%%.*}"
        MINOR="${VER#*.}"
        if [[ "$MAJOR" -gt "$PYTHON_MIN_MAJOR" ]] || \
           [[ "$MAJOR" -eq "$PYTHON_MIN_MAJOR" && "$MINOR" -ge "$PYTHON_MIN_MINOR" ]]; then
            PYTHON_CMD="$cmd"
            ok "Python $VER encontrado: $cmd"
            break
        else
            warn "Python $VER demasiado antiguo (se necesita >= ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR})"
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    err "No se encontró Python >= ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}."
    echo ""
    echo "  Instálalo desde: https://www.python.org/downloads/"
    echo "  En Ubuntu: sudo apt install python3.12"
    echo "  En macOS con Homebrew: brew install python@3.12"
    echo ""
    exit 1
fi

# ── Paso 2: Ollama ─────────────────────────────────────────────────────────────
step "2/5 · Comprobando Ollama"

if command -v ollama &>/dev/null; then
    OLLAMA_VER=$(ollama --version 2>/dev/null | head -1 || echo "desconocida")
    ok "Ollama ya está instalado ($OLLAMA_VER)"
else
    warn "Ollama no está instalado."
    echo ""
    echo "  Ollama es necesario para descargar y ejecutar modelos de IA localmente."
    echo ""
    if ask "¿Quieres instalar Ollama ahora?"; then
        info "Descargando e instalando Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama instalado."
    else
        warn "Saltando instalación de Ollama. Puedes instalarlo más tarde desde https://ollama.com"
    fi
fi

# ── Paso 3: Entorno virtual ────────────────────────────────────────────────────
step "3/5 · Entorno virtual Python"

VENV_DIR="$REPO_DIR/.venv"

if [[ -d "$VENV_DIR" ]]; then
    ok "El entorno virtual ya existe (.venv)"
else
    info "Creando entorno virtual en .venv ..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    ok "Entorno virtual creado."
fi

# Activar venv
if [[ -f "$VENV_DIR/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    ok "Entorno virtual activado."
else
    err "No se encontró el activador del entorno virtual."
    exit 1
fi

# ── Paso 4: Dependencias ───────────────────────────────────────────────────────
step "4/5 · Instalando dependencias de ci2lab"

info "Ejecutando: pip install -e '.[dev]'"
pip install --quiet --upgrade pip
pip install -e "$REPO_DIR/.[dev]"
ok "Dependencias instaladas."

# ── Paso 5: Verificación ───────────────────────────────────────────────────────
step "5/5 · Verificando la instalación"

info "Ejecutando ci2lab doctor..."
echo ""
ci2lab doctor || warn "ci2lab doctor reportó algún problema. Revisa el resultado anterior."

# ── Modelo inicial (opcional) ──────────────────────────────────────────────────
echo ""
if command -v ollama &>/dev/null; then
    if ask "¿Quieres ver los modelos recomendados para tu equipo y descargar uno ahora?"; then
        echo ""
        ci2lab models recommend
        echo ""
        echo -e "${YELLOW}  ?  Escribe el Tag Ollama del modelo que quieres descargar (o pulsa Enter para saltar):${RESET} "
        read -r MODEL_TAG
        if [[ -n "$MODEL_TAG" ]]; then
            info "Descargando $MODEL_TAG ..."
            ollama pull "$MODEL_TAG"
            ok "Modelo $MODEL_TAG descargado."
        else
            info "Saltando descarga de modelo."
        fi
    fi
fi

# ── Resumen final ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║        ¡Instalación completada!          ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${RESET}"
echo ""
echo "  Para usar ci2lab, activa primero el entorno virtual:"
echo ""
echo -e "    ${CYAN}source .venv/bin/activate${RESET}"
echo ""
echo "  Luego puedes usar:"
echo -e "    ${CYAN}ci2lab chat${RESET}              → conversación interactiva"
echo -e "    ${CYAN}ci2lab ui${RESET}                → interfaz web local"
echo -e "    ${CYAN}ci2lab models recommend${RESET}  → ver modelos disponibles"
echo ""
