# Comandos de Ci2Lab

Guia practica para empezar desde cero y, despues, consultar el resto de comandos utiles.

> Nota: el comando `ci2lab` aparece despues de instalar el paquete con `pip install -e ".[dev]"`.

## 1. Entrar en el proyecto

```powershell
cd IAmultiagentica
```
Entra en la carpeta del proyecto.

## 2. Crear y activar el entorno virtual

### Windows PowerShell

```powershell
py -m venv .venv
```
Crea el entorno virtual en Windows.

```powershell
.\.venv\Scripts\Activate.ps1
```
Activa el entorno virtual en PowerShell.

### macOS / Linux

```bash
python3 -m venv .venv
```
Crea el entorno virtual en macOS/Linux.

```bash
source .venv/bin/activate
```
Activa el entorno virtual en macOS/Linux.

## 3. Instalar dependencias

```powershell
pip install -e ".[dev]"
```
Instala Ci2Lab y dependencias de desarrollo.

## 4. Instalar Ollama

Ollama es el programa que descarga y ejecuta los modelos locales. Sin esto, `ollama pull ...` no funcionara.

### Windows PowerShell

```powershell
irm https://ollama.com/install.ps1 | iex
```
Instala Ollama desde PowerShell.

```powershell
ollama --version
```
Comprueba que Ollama quedo instalado.

```powershell
ollama serve
```
Arranca Ollama si no esta abierto en segundo plano.

### Instalacion manual

```text
https://ollama.com/download
```
Descarga el instalador oficial desde el navegador.

### macOS / Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```
Instala Ollama desde terminal.

```bash
ollama --version
```
Comprueba que Ollama quedo instalado.

```bash
ollama serve
```
Arranca Ollama si no esta abierto en segundo plano.

## 5. Comprobar que todo responde

```powershell
ci2lab doctor
```
Comprueba instalacion, paquete y conexion con Ollama.

## 6. Detectar la capacidad del ordenador

```powershell
ci2lab hardware
```
Muestra las caracteristicas detectadas del equipo.

```powershell
ci2lab hardware --json
```
Muestra el hardware detectado en JSON.

```powershell
ci2lab models recommend
```
Recomienda modelos que caben en tu ordenador.

```powershell
ci2lab models recommend --limit 3
```
Limita el numero de recomendaciones.

## 7. Recomendar modelos segun la tarea

```powershell
ci2lab models recommend "programar en Python"
```
Recomienda modelos para programacion.

```powershell
ci2lab models recommend "editar y revisar codigo"
```
Recomienda modelos para trabajar sobre codigo.

```powershell
ci2lab models recommend "razonamiento complejo"
```
Recomienda modelos para razonamiento.

```powershell
ci2lab models recommend "resumir documentos largos"
```
Recomienda modelos para resumen y contexto.

```powershell
ci2lab models recommend "usar en un ordenador con pocos recursos"
```
Recomienda modelos ligeros.

## 8. Ver como instalar el modelo elegido

Estos comandos no descargan directamente el modelo: muestran el plan y los comandos recomendados.

```powershell
ci2lab models install qwen2.5-coder-1.5b
```
Muestra comandos para instalar y usar ese modelo.

```powershell
ci2lab models install qwen2.5-coder:1.5b
```
Muestra comandos usando el tag de Ollama.

## 9. Descargar modelos con Ollama

Descarga solo los modelos que te haya recomendado `ci2lab models recommend` y que quepan en tu equipo.

```powershell
ollama pull llama3.2:1b
```
Descarga Llama 3.2 1B.

```powershell
ollama pull qwen2.5-coder:1.5b
```
Descarga Qwen2.5 Coder 1.5B.

```powershell
ollama pull llama3.2:3b
```
Descarga Llama 3.2 3B.

```powershell
ollama pull gemma2:2b
```
Descarga Gemma 2 2B.

```powershell
ollama pull mistral:7b
```
Descarga Mistral 7B.

```powershell
ollama pull qwen2.5-coder:7b
```
Descarga Qwen2.5 Coder 7B.

```powershell
ollama pull gemma2:9b
```
Descarga Gemma 2 9B.

```powershell
ollama pull phi4:14b
```
Descarga Phi-4 14B.

```powershell
ollama pull qwen2.5-coder:14b
```
Descarga Qwen2.5 Coder 14B.

```powershell
ollama pull qwen2.5-coder:32b
```
Descarga Qwen2.5 Coder 32B.

## 10. Probar un modelo descargado

```powershell
ollama run qwen2.5-coder:1.5b
```
Abre chat directo con Qwen Coder.

```powershell
ollama run llama3.1:8b
```
Abre chat directo con Ollama.

```powershell
ci2lab models run qwen2.5-coder-1.5b
```
Abre el modelo con `ollama run`.

```powershell
ci2lab models run qwen2.5-coder:1.5b
```
Abre el modelo usando el tag de Ollama.

## 11. Usar el agente por primera vez

```powershell
ci2lab chat
```
Abre el modo interactivo del agente.

```powershell
ci2lab --model qwen2.5-coder-1.5b chat
```
Abre chat agente con ese modelo.

```powershell
ci2lab "lista los archivos Python"
```
Ejecuta una peticion puntual al agente.

```powershell
ci2lab agent "lista los archivos Python"
```
Ejecuta una peticion puntual usando el subcomando explicito.

```powershell
ci2lab --workspace . --no-stream "resume este proyecto"
```
Pide un resumen del proyecto actual.

```powershell
ci2lab --workspace . --yes "ejecuta los tests y dime el resultado"
```
Permite al agente lanzar pruebas si lo necesita.

## 12. Salir de la conversacion y borrar cosas

Dentro de `ci2lab chat` o `ci2lab --model ... chat`, escribe uno de estos comandos.

```text
/exit
```
Sale de la conversacion con el agente.

```text
/quit
```
Sale de la conversacion con el agente.

```text
exit
```
Sale de la conversacion con el agente.

```text
quit
```
Sale de la conversacion con el agente.

```text
Ctrl+C
```
Interrumpe y cierra la conversacion.

Dentro de `ollama run ...`, usa este comando.

```text
/bye
```
Sale del chat directo de Ollama.

```text
Ctrl+C
```
Interrumpe el chat directo de Ollama.

Para ver sesiones guardadas de Ci2Lab.

```powershell
ci2lab sessions
```
Lista las conversaciones guardadas.

Para borrar una sesion guardada en Windows PowerShell.

```powershell
Remove-Item "$HOME\.ci2lab\sessions\<ID_DE_SESION>.json"
```
Borra una sesion concreta de Ci2Lab.

Para borrar una sesion guardada en macOS/Linux.

```bash
rm ~/.ci2lab/sessions/<ID_DE_SESION>.json
```
Borra una sesion concreta de Ci2Lab.

Para eliminar un modelo descargado en Ollama.

```powershell
ollama rm llama3.1:8b
```
Elimina el modelo `llama3.1:8b` del disco.

```powershell
ollama rm qwen2.5-coder:1.5b
```
Elimina el modelo `qwen2.5-coder:1.5b` del disco.

```powershell
ollama list
```
Muestra los modelos instalados en Ollama.

## 13. Comandos principales de uso diario

```powershell
ci2lab doctor
```
Verifica que todo esta listo.

```powershell
ci2lab chat
```
Abre una conversacion interactiva.

```powershell
ci2lab sessions
```
Lista sesiones guardadas.

```powershell
ci2lab sessions --json
```
Lista sesiones guardadas en JSON.

```powershell
ci2lab hardware
```
Consulta el hardware detectado.

```powershell
ci2lab evals run
```
Valida el harness en modo mock.

## IDs validos del catalogo

```text
llama3.2-1b
```
Modelo pequeno generalista.

```text
qwen2.5-coder-1.5b
```
Modelo pequeno orientado a codigo.

```text
llama3.2-3b
```
Modelo pequeno generalista y razonamiento ligero.

```text
gemma2-2b
```
Modelo pequeno generalista.

```text
mistral-7b
```
Modelo generalista de workstation.

```text
qwen2.5-coder-7b
```
Modelo de codigo de workstation.

```text
gemma2-9b
```
Modelo generalista mas grande.

```text
phi4-14b
```
Modelo orientado a razonamiento.

```text
qwen2.5-coder-14b
```
Modelo grande orientado a codigo.

```text
qwen2.5-coder-32b
```
Modelo grande de mayor calidad para codigo.

## Flags del agente

Estos flags se pueden usar antes del prompt o con `ci2lab agent`.

```powershell
ci2lab --model llama3.1:8b "hola"
```
Fuerza el modelo para una peticion.

```powershell
ci2lab --model qwen2.5-coder-1.5b "revisa este proyecto"
```
Fuerza un modelo por ID del catalogo.

```powershell
ci2lab --tool-mode native "haz una tarea"
```
Usa tool calling nativo.

```powershell
ci2lab --tool-mode fenced "haz una tarea"
```
Usa formato de herramientas en bloques fenced.

```powershell
ci2lab --workspace . "lista los archivos"
```
Define el directorio de trabajo del agente.

```powershell
ci2lab --cwd . "lista los archivos"
```
Alias legacy de `--workspace`.

```powershell
ci2lab --yes "ejecuta los tests"
```
Auto-confirma herramientas peligrosas permitidas.

```powershell
ci2lab --no-stream "di hola"
```
Desactiva streaming de tokens.

```powershell
ci2lab --max-rounds 10 "resuelve esto"
```
Limita las rondas del bucle agente.

```powershell
ci2lab --session mi-sesion chat
```
Reanuda o usa una sesion concreta.

```powershell
ci2lab --runs-dir ./_runs "hola"
```
Guarda logs en otro directorio.

```powershell
ci2lab --no-log "hola"
```
Ejecuta sin guardar artefactos en `runs/`.

```powershell
ci2lab --workspace . --runs-dir ./_test_runs --no-stream --yes "hola"
```
Prueba agente con workspace, logs personalizados y sin streaming.

```powershell
ci2lab --no-log --no-stream --yes "lista los archivos"
```
Ejecuta rapido sin streaming ni logs.

## Evaluaciones

```powershell
ci2lab evals run
```
Ejecuta evals mock sin Ollama.

```powershell
python -m ci2lab.evals.run
```
Entrypoint directo de evals mock.

```powershell
ci2lab evals run --live
```
Ejecuta evals contra Ollama real.

```powershell
ci2lab evals run --live --model llama3.1:8b
```
Ejecuta evals live con modelo concreto.

```powershell
ci2lab evals run --task 001_list_files
```
Ejecuta solo una tarea de evaluacion.

```powershell
ci2lab evals run --task 001_list_files --task 002_read_file
```
Ejecuta varias tareas concretas.

```powershell
ci2lab evals run --tasks-dir ./evals/tasks
```
Usa un directorio personalizado de tareas.

```powershell
python -m ci2lab.evals.run --task 006_edit_file_approved
```
Ejecuta una tarea concreta desde Python.

```powershell
python -m ci2lab.evals.run --live --model llama3.1:8b --task 001_list_files
```
Ejecuta una tarea live con modelo concreto.

```powershell
python -m ci2lab.evals.run --live --model llama3.1:8b
```
Ejecuta toda la suite live.

## Tests y comprobaciones de desarrollo

```powershell
python -m pytest tests/ -q
```
Ejecuta la suite automatizada.

```powershell
python -m ci2lab.cli --help
```
Muestra ayuda del CLI principal.

```powershell
python -m ci2lab --help
```
Muestra ayuda usando el entrypoint de paquete.

```powershell
python -m ci2lab.cli --workspace . --help
```
Muestra ayuda con flags del agente.

```powershell
python -m ci2lab.cli doctor
```
Ejecuta `doctor` sin usar el script instalado.

```powershell
python -m ci2lab.cli --no-stream --yes "lista los archivos"
```
Ejecuta el agente desde el modulo Python.

```powershell
python -m ci2lab.cli --no-log --no-stream --yes "lista los archivos"
```
Ejecuta sin logs ni streaming desde Python.

## Logging de ejecuciones

```powershell
ci2lab --workspace . "lista los archivos"
```
Guarda una ejecucion normal en `runs/`.

```powershell
ci2lab --no-log "lista los archivos"
```
Desactiva logging para esa ejecucion.

```powershell
ci2lab --runs-dir ./_runs "hola"
```
Guarda artefactos en `./_runs`.

```powershell
$env:CI2LAB_NO_LOG="1"
```
Desactiva logs por variable de entorno.

```powershell
$env:CI2LAB_RUNS_DIR="./_runs"
```
Define carpeta de logs por variable de entorno.

## Configuracion por variables de entorno

```powershell
$env:CI2LAB_MODEL="llama3.1:8b"
```
Define el modelo por defecto.

```powershell
$env:CI2LAB_OLLAMA_URL="http://localhost:11434"
```
Define la URL base de Ollama.

```powershell
$env:CI2LAB_BACKEND_URL="http://localhost:11434/v1"
```
Define endpoint OpenAI-compatible.

```powershell
$env:CI2LAB_TOOL_MODE="native"
```
Define modo de herramientas.

```powershell
$env:CI2LAB_MAX_ROUNDS="25"
```
Define maximo de rondas.

```powershell
$env:CI2LAB_WORKSPACE="."
```
Define workspace por defecto.

```powershell
$env:CI2LAB_CWD="."
```
Alias legacy para workspace.

```powershell
$env:CI2LAB_STREAM="false"
```
Desactiva streaming por defecto.

```powershell
$env:CI2LAB_AUTO_CONFIRM="1"
```
Activa auto-confirmacion.

```powershell
$env:CI2LAB_YES="1"
```
Activa auto-confirmacion.

```powershell
$env:CI2LAB_CONFIG="./ci2lab.yaml"
```
Fuerza ruta de archivo de configuracion.

```powershell
$env:CI2LAB_WRITE_TOOLS_ENABLED="false"
```
Desactiva `write_file` y `edit_file`.

```powershell
$env:CI2LAB_REQUIRE_DIFF_PREVIEW="false"
```
Permite saltar preview obligatorio de edicion.

## Configuracion por archivo

Crear `ci2lab.yaml` en la raiz o `~/.ci2lab/ci2lab.yaml`.

```yaml
model: llama3.1:8b
runs_dir: runs
log_runs: true
```
Configura modelo y logging.

```yaml
workspace: .
max_rounds: 25
stream: true
auto_confirm: false
```
Configura workspace y comportamiento del agente.

```yaml
backend_url: http://localhost:11434/v1
tool_mode: native
```
Configura endpoint y modo de tools.

```yaml
write_tools_enabled: false
```
Desactiva herramientas de escritura.

```yaml
require_diff_preview: true
```
Mantiene diff obligatorio antes de editar.

```yaml
no_log: true
```
Desactiva logging desde YAML.

## Herramientas internas del agente

Estas no se ejecutan normalmente a mano; el modelo las invoca durante una tarea.

```text
ls
```
Lista directorios del workspace.

```text
read_file
```
Lee archivos con lineas numeradas.

```text
grep
```
Busca regex en archivos.

```text
glob
```
Encuentra archivos por patron.

```text
bash
```
Ejecuta comandos shell con confirmacion y blocklist.

```text
write_file
```
Crea o sobrescribe archivos con supervision.

```text
edit_file
```
Edita por reemplazo exacto con diff preview.

## Tareas de eval incluidas

```text
001_list_files
```
Comprueba uso de `ls`.

```text
002_read_file
```
Comprueba uso de `read_file`.

```text
003_find_function
```
Comprueba busqueda con `grep` o `glob` y `read_file`.

```text
004_block_dangerous_bash
```
Comprueba bloqueo de comandos peligrosos.

```text
005_edit_file_denied
```
Comprueba edicion supervisada denegada.

```text
006_edit_file_approved
```
Comprueba edicion supervisada aprobada.

```text
007_write_tools_disabled
```
Comprueba bloqueo de escritura por configuracion.

## Secuencia rapida recomendada

```powershell
cd IAmultiagentica
```
Entra en el proyecto.

```powershell
py -m venv .venv
```
Crea el entorno virtual.

```powershell
.\.venv\Scripts\Activate.ps1
```
Activa el entorno virtual.

```powershell
pip install -e ".[dev]"
```
Instala dependencias.

```powershell
irm https://ollama.com/install.ps1 | iex
```
Instala Ollama en Windows.

```powershell
ollama --version
```
Comprueba que Ollama esta instalado.

```powershell
ci2lab doctor
```
Comprueba el entorno.

```powershell
ci2lab hardware
```
Detecta la capacidad del equipo.

```powershell
ci2lab models recommend "programar en Python"
```
Elige un modelo para tu caso.

```powershell
ci2lab models install qwen2.5-coder-1.5b
```
Obtiene el comando de instalacion del modelo.

```powershell
ollama pull qwen2.5-coder:1.5b
```
Descarga el modelo en Ollama.

```powershell
ci2lab --model qwen2.5-coder-1.5b chat
```
Abre chat agente con ese modelo.
