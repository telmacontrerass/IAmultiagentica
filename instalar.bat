@echo off
:: instalar.bat — Lanzador de doble clic para Windows
:: Llama a instalar.ps1 con los permisos necesarios para ejecutar scripts.

cd /d "%~dp0"

echo.
echo  Iniciando instalador de ci2lab...
echo  (Al terminar, ci2lab quedara disponible desde cualquier carpeta)
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] El instalador termino con errores.
    echo  Revisa los mensajes anteriores.
    echo.
    pause
)
