# instalar.ps1 - Instalador automatico de ci2lab para Windows
# Compatible con Windows PowerShell 5.1+
# Ejecucion: .\instalar.bat  (recomendado) o .\instalar.ps1

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonMin = [Version]"3.11"

function Ok($msg)   { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!]   $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "  [X]   $msg" -ForegroundColor Red }
function Info($msg) { Write-Host "  -->   $msg" -ForegroundColor Cyan }
function Step($msg) { Write-Host ""; Write-Host "[ $msg ]" -ForegroundColor White }

function Ask($msg) {
    Write-Host "  [?]   $msg [s/N] " -ForegroundColor Yellow -NoNewline
    $resp = Read-Host
    return $resp -match "^[sS]$"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor White
Write-Host "       Instalador de ci2lab               " -ForegroundColor White
Write-Host "==========================================" -ForegroundColor White
Write-Host ""
Info "Directorio del proyecto: $RepoDir"

function Ensure-PathContains([string]$dir) {
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($userPath) {
        $parts = $userPath -split ";" | Where-Object { $_ -and $_.Trim() -ne "" }
    }
    if ($parts -contains $dir) {
        return $false
    }
    $newPath = if ($userPath -and $userPath.Trim()) { "$userPath;$dir" } else { $dir }
    [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = $env:Path + ";" + $dir
    return $true
}

# Paso 1: Python
Step "1/5 - Comprobando Python"

$PythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $verStr = & $cmd -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))" 2>$null
        if ($verStr) {
            $ver = [Version]$verStr.Trim()
            if ($ver -ge $PythonMin) {
                $PythonCmd = $cmd
                Ok "Python $verStr encontrado ($cmd)"
                break
            } else {
                Warn "Python $verStr demasiado antiguo (se necesita >= $PythonMin)"
            }
        }
    } catch {
        # probar siguiente comando
    }
}

if (-not $PythonCmd) {
    Err "No se encontro Python >= $PythonMin."
    Write-Host ""
    Write-Host "  Instalalo desde: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Asegurate de marcar 'Add Python to PATH' durante la instalacion." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Pulsa Enter para cerrar"
    exit 1
}

# Paso 2: Ollama
Step "2/5 - Comprobando Ollama"

$ollamaInstalled = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)

if ($ollamaInstalled) {
    $ollamaVer = ollama --version 2>$null | Select-Object -First 1
    if (-not $ollamaVer) {
        $ollamaVer = "version desconocida"
    }
    Ok "Ollama ya esta instalado ($ollamaVer)"
} else {
    Warn "Ollama no esta instalado."
    Write-Host ""
    Write-Host "  Ollama es necesario para descargar y ejecutar modelos de IA localmente." -ForegroundColor White
    Write-Host ""
    if (Ask "Quieres instalar Ollama ahora?") {
        Info "Descargando e instalando Ollama..."
        $ollamaInstaller = Join-Path $env:TEMP "OllamaSetup.exe"
        try {
            Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" `
                -OutFile $ollamaInstaller -UseBasicParsing
            Info "Ejecutando instalador de Ollama (sigue los pasos que aparezcan)..."
            Start-Process -FilePath $ollamaInstaller -Wait
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("Path", "User")
            if ($null -ne (Get-Command ollama -ErrorAction SilentlyContinue)) {
                Ok "Ollama instalado correctamente."
            } else {
                Warn "Ollama instalado pero no esta en PATH todavia. Puede que necesites reiniciar la terminal."
            }
        } catch {
            Warn "No se pudo descargar Ollama automaticamente."
            Write-Host "  Descargalo manualmente desde: https://ollama.com/download" -ForegroundColor Yellow
        }
    } else {
        Warn "Saltando instalacion de Ollama. Puedes instalarlo mas tarde desde https://ollama.com"
    }
}

# Paso 3: Entorno virtual
Step "3/5 - Entorno virtual Python"

$VenvDir = Join-Path $RepoDir ".venv"

if (Test-Path $VenvDir) {
    Ok "El entorno virtual ya existe (.venv)"
} else {
    Info "Creando entorno virtual en .venv ..."
    & $PythonCmd -m venv $VenvDir
    Ok "Entorno virtual creado."
}

$Activate = Join-Path $VenvDir "Scripts\Activate.ps1"
if (-not (Test-Path $Activate)) {
    Err "No se encontro el activador del entorno virtual: $Activate"
    Read-Host "Pulsa Enter para cerrar"
    exit 1
}
& $Activate
Ok "Entorno virtual activado."

# Paso 4: Dependencias
Step "4/5 - Instalando dependencias de ci2lab"

Info "Actualizando pip..."
python -m pip install --quiet --upgrade pip
Info "Ejecutando: pip install -e '.[dev]'"
python -m pip install -e (Join-Path $RepoDir ".[dev]")
Ok "Dependencias instaladas."

# Paso 5: Comando global + verificacion
Step "5/5 - Registrando comando global y verificando"

$Ci2labBin = Join-Path $env:USERPROFILE ".ci2lab\bin"
New-Item -ItemType Directory -Force -Path $Ci2labBin | Out-Null
$LauncherCmd = Join-Path $Ci2labBin "ci2lab.cmd"
$LauncherShim = @"
@echo off
setlocal
"$RepoDir\.venv\Scripts\python.exe" -m ci2lab.cli %*
"@
$LauncherShim | Set-Content -Path $LauncherCmd -Encoding ASCII
Ok "Lanzador global creado: $LauncherCmd"

if (Ensure-PathContains $Ci2labBin) {
    Ok "PATH de usuario actualizado con: $Ci2labBin"
} else {
    Ok "PATH ya contiene: $Ci2labBin"
}

Info "Ejecutando ci2lab doctor..."
Write-Host ""
try {
    ci2lab doctor
} catch {
    Warn "ci2lab doctor reporto algun problema. Revisa el resultado anterior."
}

# Modelo inicial (opcional)
Write-Host ""
if ($null -ne (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (Ask "Quieres ver los modelos recomendados para tu equipo y descargar uno ahora?") {
        Write-Host ""
        ci2lab models recommend
        Write-Host ""
        Write-Host "  [?]   Escribe el Tag Ollama del modelo que quieres descargar (Enter para saltar): " `
            -ForegroundColor Yellow -NoNewline
        $ModelTag = Read-Host
        if ($ModelTag) {
            Info "Descargando $ModelTag ..."
            ollama pull $ModelTag
            Ok "Modelo $ModelTag descargado."
        } else {
            Info "Saltando descarga de modelo."
        }
    }
}

# Resumen final
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "        Instalacion completada!           " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Ya puedes usar ci2lab desde cualquier carpeta (sin activar .venv)."
Write-Host ""
Write-Host "  Si no se reconoce el comando en una terminal antigua, abre una nueva."
Write-Host ""
Write-Host "  Luego puedes usar:"
Write-Host "    ci2lab chat              -> conversacion interactiva" -ForegroundColor Cyan
Write-Host "    ci2lab ui                -> interfaz web local" -ForegroundColor Cyan
Write-Host "    ci2lab --workspace . chat -> usar el proyecto abierto en VS Code" -ForegroundColor Cyan
Write-Host "    ci2lab models recommend  -> ver modelos disponibles" -ForegroundColor Cyan
Write-Host ""
Read-Host "Pulsa Enter para cerrar"
