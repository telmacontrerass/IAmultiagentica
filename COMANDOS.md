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

## 8. Patron para usar cualquier modelo

En la tabla de abajo, `ci2lab` acepta tanto `ID Ci2Lab` como `Tag Ollama`. Si uno falla porque Ollama no encuentra el modelo, Ci2Lab intenta el alias alternativo automaticamente.

Para comandos `ollama`, usa siempre `Tag Ollama`.

```powershell
ci2lab models install <MODELO_ID>
```
Muestra el plan para instalar y usar el modelo.

```powershell
ollama pull <OLLAMA_TAG>
```
Descarga el modelo en Ollama.

```powershell
ci2lab models run <MODELO_ID>
```
Abre el modelo desde Ci2Lab con `ollama run`.

```powershell
ci2lab --model <MODELO_ID> chat
```
Abre chat agente con ese modelo.

```powershell
ci2lab --model <MODELO_ID> "hola"
```
Ejecuta una peticion puntual con ese modelo.

```powershell
ollama rm <OLLAMA_TAG>
```
Elimina el modelo descargado del disco.

```powershell
ollama list
```
Muestra los modelos instalados en Ollama.

## 9. Tabla de modelos disponibles

El catalogo actual tiene 64 modelos. Descarga solo los que te recomiende `ci2lab models recommend` y que quepan en tu equipo.

| Modelo | ID Ci2Lab | Tag Ollama | Uso | Tier | RAM aprox. |
|---|---|---|---|---|---|
| Llama 3.2 1B | `llama3.2-1b` | `llama3.2:1b` | general, edge | edge | 2 GB |
| Qwen2.5 Coder 1.5B | `qwen2.5-coder-1.5b` | `qwen2.5-coder:1.5b` | coding, edge | edge | 3 GB |
| Llama 3.2 3B | `llama3.2-3b` | `llama3.2:3b` | general, reasoning, edge | edge | 5 GB |
| Gemma 2 2B | `gemma2-2b` | `gemma2:2b` | general, edge | edge | 4 GB |
| TinyLlama 1.1B Chat | `tinyllama-1.1b` | `tinyllama:1.1b` | general, edge | edge | 2 GB |
| Qwen2.5 3B Instruct | `qwen2.5-3b` | `qwen2.5:3b` | general, reasoning, edge | edge | 4 GB |
| Phi-3 Mini 4K Instruct | `phi3-mini` | `phi3:mini` | general, reasoning, edge | edge | 4 GB |
| Phi-3.5 Mini Instruct | `phi3.5-3.8b` | `phi3.5:3.8b` | general, reasoning, edge | edge | 4 GB |
| Qwen3 4B Instruct | `qwen3-4b` | `qwen3:4b` | general, reasoning | edge | 4.5 GB |
| Qwen1.5 0.5B | `qwen-0-5b` | `qwen:0.5b` | general, edge | edge | 2 GB |
| Qwen1.5 1.8B | `qwen-1-8b` | `qwen:1.8b` | general, edge | edge | 2 GB |
| Qwen2 1.5B | `qwen2-1-5b` | `qwen2:1.5b` | general, edge | edge | 2 GB |
| Qwen2.5 1.5B | `qwen2.5-1-5b` | `qwen2.5:1.5b` | general, edge | edge | 2 GB |
| Qwen3 0.6B | `qwen3-0-6b` | `qwen3:0.6b` | general, edge | edge | 2 GB |
| Qwen3 1.7B Base | `qwen3-1-7b` | `qwen3:1.7b` | general, edge | edge | 2 GB |
| Qwen2.5 Coder 3B | `qwen2.5-coder-3b` | `qwen2.5-coder:3b` | coding, edge | edge | 2.9 GB |
| starcoder2 3b | `starcoder2-3b` | `starcoder2:3b` | coding, edge | edge | 2.8 GB |
| Mistral 7B Instruct | `mistral-7b` | `mistral:7b` | general, reasoning | workstation | 8 GB |
| Falcon 7B Instruct | `falcon-7b` | `falcon:7b` | general, reasoning | workstation | 6.8 GB |
| DeepSeek Coder 6.7B Instruct | `deepseek-coder-6.7b` | `deepseek-coder:6.7b` | coding, general | workstation | 6.5 GB |
| Qwen2.5 7B Instruct | `qwen2.5-7b` | `qwen2.5:7b` | general, reasoning | workstation | 7.2 GB |
| DeepSeek R1 Distill 7B | `deepseek-r1-7b` | `deepseek-r1:7b` | reasoning, general, coding | workstation | 7.2 GB |
| Llama 3 8B Instruct | `llama3-8b` | `llama3:8b` | general, reasoning | workstation | 7.5 GB |
| Granite 3.3 8B Instruct | `granite3.3-8b` | `granite3.3:8b` | general, reasoning | workstation | 7.6 GB |
| Qwen2.5 Coder 7B | `qwen2.5-coder-7b` | `qwen2.5-coder:7b` | coding, general, reasoning | workstation | 9 GB |
| Gemma 2 9B | `gemma2-9b` | `gemma2:9b` | general, reasoning | workstation | 12 GB |
| Phi-4 14B | `phi4-14b` | `phi4:14b` | reasoning, coding, general | workstation | 16 GB |
| Qwen2.5 Coder 14B | `qwen2.5-coder-14b` | `qwen2.5-coder:14b` | coding, reasoning, general | workstation | 18 GB |
| CodeLlama 7b Instruct | `codellama-7b` | `codellama:7b` | coding | workstation | 6.3 GB |
| vicuna 7b v1.5 | `vicuna-7b` | `vicuna:7b` | general | workstation | 6.3 GB |
| openchat 3.5 0106 | `openchat-7b` | `openchat:7b` | general | workstation | 6.5 GB |
| starcoder2 7b | `starcoder2-7b` | `starcoder2:7b` | coding | workstation | 6.7 GB |
| zephyr 7b beta | `zephyr-7b` | `zephyr:7b` | general | workstation | 6.7 GB |
| Falcon3 7B | `falcon3-7b` | `falcon3:7b` | general | workstation | 6.9 GB |
| Qwen1.5 7B | `qwen-7b` | `qwen:7b` | general | workstation | 7.2 GB |
| Qwen2 7B | `qwen2-7b` | `qwen2:7b` | general | workstation | 7.1 GB |
| Hermes 3 Llama 3.1 8B | `hermes3-8b` | `hermes3:8b` | general | workstation | 7.5 GB |
| Qwen3 8B Base | `qwen3-8b` | `qwen3:8b` | general | workstation | 7.6 GB |
| Yi 1.5 9B | `yi-9b` | `yi:9b` | general | workstation | 8.2 GB |
| glm 4 9b | `glm4-9b` | `glm4:9b` | general | workstation | 8.8 GB |
| SOLAR 10.7B Instruct v1.0 | `solar-10-7b` | `solar:10.7b` | general | workstation | 10 GB |
| Mistral Nemo Instruct 2407 | `mistral-nemo-12b` | `mistral-nemo:12b` | general | workstation | 11.4 GB |
| vicuna 13b v1.5 | `vicuna-13b` | `vicuna:13b` | general | workstation | 12.1 GB |
| Qwen2.5 14B | `qwen2.5-14b` | `qwen2.5:14b` | general | workstation | 13.7 GB |
| DeepSeek R1 Distill Qwen 14B | `deepseek-r1-14b` | `deepseek-r1:14b` | reasoning | workstation | 13.8 GB |
| Qwen3 14B AWQ | `qwen3-14b` | `qwen3:14b` | general | workstation | 13.8 GB |
| starcoder2 15b | `starcoder2-15b` | `starcoder2:15b` | coding | workstation | 14.6 GB |
| Qwen2.5 Coder 32B | `qwen2.5-coder-32b` | `qwen2.5-coder:32b` | coding, reasoning, general | enterprise | 32 GB |
| gemma 2 27b | `gemma2-27b` | `gemma2:27b` | general | enterprise | 25.4 GB |
| Qwen3 30B A3B GPTQ Int4 | `qwen3-30b` | `qwen3:30b` | general | enterprise | 28.4 GB |
| Qwen1.5 32B | `qwen-32b` | `qwen:32b` | general | enterprise | 30.3 GB |
| Qwen2.5 32B | `qwen2.5-32b` | `qwen2.5:32b` | general | enterprise | 30.3 GB |
| DeepSeek R1 Distill Qwen 32B | `deepseek-r1-32b` | `deepseek-r1:32b` | reasoning | enterprise | 30.5 GB |
| Qwen3 32B AWQ | `qwen3-32b` | `qwen3:32b` | general | enterprise | 30.5 GB |
| falcon 40b | `falcon-40b` | `falcon:40b` | general | enterprise | 37.3 GB |
| Mixtral 8x7B Instruct v0.1 | `mixtral-8x7b` | `mixtral:8x7b` | general | enterprise | 43.5 GB |
| Llama 3.1 70B | `llama3.1-70b` | `llama3.1:70b` | general | enterprise | 65.7 GB |
| Llama 3.3 70B | `llama3.3-70b` | `llama3.3:70b` | general | enterprise | 65.7 GB |
| Qwen2 72B | `qwen2-72b` | `qwen2:72b` | general | enterprise | 67.7 GB |
| Qwen2.5 72B | `qwen2.5-72b` | `qwen2.5:72b` | general | enterprise | 67.7 GB |
| Qwen1.5 110B Chat AWQ | `qwen-110b` | `qwen:110b` | general | enterprise | 103.6 GB |
| Mixtral 8x22B Instruct v0.1 | `mixtral-8x22b` | `mixtral:8x22b` | general | enterprise | 131 GB |
| Qwen3 235B A22B | `qwen3-235b` | `qwen3:235b` | general | enterprise | 218.9 GB |
| Llama 3.1 405B | `llama3.1-405b` | `llama3.1:405b` | general | enterprise | 378 GB |

Ejemplo de sustitucion: para Qwen2.5 Coder 1.5B, `<MODELO_ID>` es `qwen2.5-coder-1.5b` y `<OLLAMA_TAG>` es `qwen2.5-coder:1.5b`.

## 10. Usar el agente por primera vez

### Modo facil con interfaz web

```powershell
ci2lab ui
```
Abre una interfaz web local para usar Ci2Lab sin escribir comandos.

```powershell
ci2lab --model <MODELO_ID> ui
```
Abre la interfaz web usando un modelo concreto por defecto.

```powershell
ci2lab ui --no-open
```
Arranca el servidor local sin abrir el navegador.

```powershell
ci2lab ui --port 8766
```
Arranca la interfaz en otro puerto local.

La UI funciona solo en local, usa Ollama como motor y mantiene sesiones/logs en tu equipo.

### Modo terminal

```powershell
ci2lab chat
```
Abre el modo interactivo con el modelo por defecto.

```powershell
ci2lab --model <MODELO_ID> chat
```
Abre chat agente con el modelo elegido en la tabla.

Si acabas de descargar un modelo concreto, usa siempre `--model <MODELO_ID>` para evitar que Ci2Lab intente abrir el modelo por defecto.

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

## 11. Salir de la conversacion y borrar cosas

Dentro de `ci2lab chat` o `ci2lab --model ... chat`, escribe uno de estos comandos.

| Comando | Hace |
|---|---|
| `/exit` | Sale de la conversacion con el agente |
| `/quit` | Sale de la conversacion con el agente |
| `exit` | Sale de la conversacion con el agente |
| `quit` | Sale de la conversacion con el agente |
| `Ctrl+C` | Interrumpe y cierra la conversacion |

Dentro de `ollama run ...`, usa este comando.

| Comando | Hace |
|---|---|
| `/bye` | Sale del chat directo de Ollama |
| `Ctrl+C` | Interrumpe el chat directo de Ollama |

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
ollama rm <OLLAMA_TAG>
```
Elimina del disco el modelo indicado en la tabla.

```powershell
ollama list
```
Muestra los modelos instalados en Ollama.

## 12. Comandos principales de uso diario

```powershell
ci2lab doctor
```
Verifica que todo esta listo.

```powershell
ci2lab chat
```
Abre una conversacion interactiva.

```powershell
ci2lab ui
```
Abre la interfaz web local.

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

## Flags del agente

Estos flags se pueden usar antes del prompt o con `ci2lab agent`.

```powershell
ci2lab --model <MODELO_ID> "hola"
```
Fuerza un modelo de la tabla para una peticion.

```powershell
ci2lab --model <OLLAMA_TAG> "revisa este proyecto"
```
Fuerza un modelo usando el tag de Ollama.

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
ci2lab models install <MODELO_ID>
```
Obtiene el comando de instalacion del modelo.

```powershell
ollama pull <OLLAMA_TAG>
```
Descarga el modelo en Ollama.

```powershell
ci2lab --model <MODELO_ID> chat
```
Abre chat agente con ese modelo.
