# Ci2Lab Commands

A practical guide to get started from scratch and then look up the rest of the useful commands.

> Note: the `ci2lab` command becomes available after you install the package with `pip install -e ".[dev]"`.

## 1. Enter the project

```powershell
cd IAmultiagentica
```
Enter the project folder.

## 2. Create and activate the virtual environment

### Windows PowerShell

```powershell
py -m venv .venv
```
Create the virtual environment on Windows.

```powershell
.\.venv\Scripts\Activate.ps1
```
Activate the virtual environment in PowerShell.

### macOS / Linux

```bash
python3 -m venv .venv
```
Create the virtual environment on macOS/Linux.

```bash
source .venv/bin/activate
```
Activate the virtual environment on macOS/Linux.

## 3. Install dependencies

```powershell
pip install -e ".[dev]"
```
Install Ci2Lab and the development dependencies.

## 4. Install Ollama

Ollama is the program that downloads and runs the local models. Without it, `ollama pull ...` will not work.

### Windows PowerShell

```powershell
irm https://ollama.com/install.ps1 | iex
```
Install Ollama from PowerShell.

```powershell
ollama --version
```
Check that Ollama was installed.

```powershell
ollama serve
```
Start Ollama if it is not already running in the background.

### Manual install

```text
https://ollama.com/download
```
Download the official installer from your browser.

### macOS / Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```
Install Ollama from the terminal.

```bash
ollama --version
```
Check that Ollama was installed.

```bash
ollama serve
```
Start Ollama if it is not already running in the background.

## 5. Check that everything responds

```powershell
ci2lab doctor
```
Check the installation, the package, and the connection to Ollama.

## 6. Detect your computer's capacity

```powershell
ci2lab hardware
```
Show the detected characteristics of your machine.

```powershell
ci2lab hardware --json
```
Show the detected hardware as JSON.

```powershell
ci2lab models recommend
```
Recommend models that fit your computer.

```powershell
ci2lab models recommend --limit 3
```
Limit the number of recommendations.

## 7. Recommend models by task

```powershell
ci2lab models recommend "program in Python"
```
Recommend models for programming.

```powershell
ci2lab models recommend "edit and review code"
```
Recommend models for working on code.

```powershell
ci2lab models recommend "complex reasoning"
```
Recommend models for reasoning.

```powershell
ci2lab models recommend "summarize long documents"
```
Recommend models for summarization and large context.

```powershell
ci2lab models recommend "run on a low-resource computer"
```
Recommend lightweight models.

## 8. Pattern for using any model

In the table below, `ci2lab` accepts either the `Ci2Lab ID` or the `Ollama Tag`. If one fails because Ollama cannot find the model, Ci2Lab tries the alternate alias automatically.

For `ollama` commands, always use the `Ollama Tag`.

```powershell
ci2lab models install <MODEL_ID>
```
Show the plan to install and use the model.

```powershell
ollama pull <OLLAMA_TAG>
```
Download the model in Ollama.

```powershell
ci2lab models run <MODEL_ID>
```
Open the model from Ci2Lab with `ollama run`.

```powershell
ci2lab --model <MODEL_ID> chat
```
Open an agent chat with that model.

```powershell
ci2lab --model <MODEL_ID> "hello"
```
Run a one-off request with that model.

```powershell
ollama rm <OLLAMA_TAG>
```
Delete the downloaded model from disk.

```powershell
ollama list
```
Show the models installed in Ollama.

## 9. Table of available models

The current catalog has 86 models. Download only the ones that `ci2lab models recommend` suggests and that fit on your machine.

| Model | Ci2Lab ID | Ollama Tag | Use | Tier | Approx. RAM |
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

Substitution example: for Qwen2.5 Coder 1.5B, `<MODEL_ID>` is `qwen2.5-coder-1.5b` and `<OLLAMA_TAG>` is `qwen2.5-coder:1.5b`.

## 10. Using the agent for the first time

### Easy mode with the web interface

```powershell
ci2lab ui
```
Open a local web interface to use Ci2Lab without typing commands.

```powershell
ci2lab --model <MODEL_ID> ui
```
Open the web interface with a specific default model.

```powershell
ci2lab ui --no-open
```
Start the local server without opening the browser.

```powershell
ci2lab ui --port 8766
```
Start the interface on a different local port.

The UI runs only locally, uses Ollama as its engine, and keeps sessions/logs on your machine.
In the chat you can attach PDFs and text files; they are copied to `ci2lab_uploads/` and the agent reads them with `read_file` (or `read_document`).
The chat page shows a persistent token counter per turn and per conversation. Click the arrow next to the counter to see how it is computed for the selected model, with links to the Ollama documentation.

> Note: as of this writing the web frontend (page text and labels) is still in Spanish; the agent's answers follow the model. See [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

### Terminal mode

```powershell
ci2lab chat
```
Open interactive mode with the default model.
After each interaction it shows the input, output, turn, and conversation tokens when Ollama returns that data.

```powershell
ci2lab --model <MODEL_ID> chat
```
Open an agent chat with the model you picked from the table.

If you have just downloaded a specific model, always use `--model <MODEL_ID>` so Ci2Lab does not try to open the default model.

```powershell
ci2lab "list the Python files"
```
Run a one-off request to the agent.

```powershell
ci2lab agent "list the Python files"
```
Run a one-off request using the explicit subcommand.

```powershell
ci2lab --workspace . --no-stream "summarize this project"
```
Ask for a summary of the current project.

```powershell
ci2lab --workspace . --yes "run the tests and tell me the result"
```
Let the agent run the tests if it needs to.

## 11. Leaving the conversation and deleting things

Inside `ci2lab chat` or `ci2lab --model ... chat`, type one of these commands.

| Command | Action |
|---|---|
| `/exit` | Leave the conversation with the agent |
| `/quit` | Leave the conversation with the agent |
| `exit` | Leave the conversation with the agent |
| `quit` | Leave the conversation with the agent |
| `Ctrl+C` | Interrupt and close the conversation |

Inside `ollama run ...`, use this command.

| Command | Action |
|---|---|
| `/bye` | Leave Ollama's direct chat |
| `Ctrl+C` | Interrupt Ollama's direct chat |

To see your saved Ci2Lab sessions.

```powershell
ci2lab sessions
```
List the saved conversations.

To delete a saved session on Windows PowerShell.

```powershell
Remove-Item "$HOME\.ci2lab\sessions\<SESSION_ID>.json"
```
Delete a specific Ci2Lab session.

To delete a saved session on macOS/Linux.

```bash
rm ~/.ci2lab/sessions/<SESSION_ID>.json
```
Delete a specific Ci2Lab session.

To remove a downloaded model in Ollama.

```powershell
ollama rm <OLLAMA_TAG>
```
Delete the model from disk.

```powershell
ollama list
```
Show the models installed in Ollama.

## 12. Main day-to-day commands

```powershell
ci2lab doctor
```
Verify that everything is ready.

```powershell
ci2lab chat
```
Open an interactive conversation.

```powershell
ci2lab ui
```
Open the local web interface.

```powershell
ci2lab sessions
```
List saved sessions.

```powershell
ci2lab sessions --json
```
List saved sessions as JSON.

```powershell
ci2lab hardware
```
Show the detected hardware.

```powershell
ci2lab evals run
```
Validate the harness in mock mode.

## Agent flags

These flags can be used before the prompt or with `ci2lab agent`.

```powershell
ci2lab --model <MODEL_ID> "hello"
```
Force a model from the table for one request.

```powershell
ci2lab --model <OLLAMA_TAG> "review this project"
```
Force a model using its Ollama tag.

```powershell
ci2lab --tool-mode native "do a task"
```
Use native tool calling.

```powershell
ci2lab --tool-mode fenced "do a task"
```
Use the fenced-block tool format.

```powershell
ci2lab --workspace . "list the files"
```
Set the agent's working directory.

```powershell
ci2lab --cwd . "list the files"
```
Legacy alias of `--workspace`.

```powershell
ci2lab --yes "run the tests"
```
Auto-confirm allowed dangerous tools.

```powershell
ci2lab --security-engine ci2lab "do a task"
```
Use the legacy security engine (no deny/ask/allow rules). The default is `claude_experimental`.

```powershell
ci2lab --no-stream "say hello"
```
Disable token streaming.

```powershell
ci2lab --max-rounds 10 "solve this"
```
Limit the agent loop rounds.

```powershell
ci2lab --session my-session chat
```
Resume or use a specific session.

```powershell
ci2lab --runs-dir ./_runs "hello"
```
Save logs in a different directory.

```powershell
ci2lab --no-log "hello"
```
Run without saving artifacts under `runs/`.

```powershell
ci2lab --workspace . --runs-dir ./_test_runs --no-stream --yes "hello"
```
Test the agent with a custom workspace, custom logs, and no streaming.

```powershell
ci2lab --no-log --no-stream --yes "list the files"
```
Run quickly with no streaming and no logs.

```powershell
ci2lab --multi-agent chat
```
Use the sequential subagent orchestrator. Note: the `--multi-agent` orchestrator is not present in this checkout; only the shared subsystems live here.

## Evaluations

```powershell
ci2lab evals run
```
Run the mock evals without Ollama.

```powershell
python -m ci2lab.evals.run
```
Direct entrypoint for the mock evals.

```powershell
ci2lab evals run --live
```
Run the evals against a real Ollama.

```powershell
ci2lab evals run --live --model llama3.1:8b
```
Run the live evals with a specific model.

```powershell
ci2lab evals run --task 001_list_files
```
Run a single evaluation task.

```powershell
ci2lab evals run --task 001_list_files --task 002_read_file
```
Run several specific tasks.

```powershell
ci2lab evals run --tasks-dir ./evals/tasks
```
Use a custom tasks directory.

```powershell
python -m ci2lab.evals.run --task 006_edit_file_approved
```
Run a specific task from Python.

```powershell
python -m ci2lab.evals.run --live --model llama3.1:8b --task 001_list_files
```
Run a live task with a specific model.

```powershell
python -m ci2lab.evals.run --live --model llama3.1:8b
```
Run the full live suite.

## Tests and development checks

```powershell
python -m pytest tests/ -q
```
Run the automated test suite.

```powershell
python -m ci2lab.cli --help
```
Show the main CLI help.

```powershell
python -m ci2lab --help
```
Show the help using the package entrypoint.

```powershell
python -m ci2lab.cli --workspace . --help
```
Show the help with the agent flags.

```powershell
python -m ci2lab.cli doctor
```
Run `doctor` without using the installed script.

```powershell
python -m ci2lab.cli --no-stream --yes "list the files"
```
Run the agent from the Python module.

```powershell
python -m ci2lab.cli --no-log --no-stream --yes "list the files"
```
Run without logs or streaming from Python.

## Workspace extensions

Skills, MCP, and project memory are configured in the working directory (they are not CLI flags).

```text
.ci2lab/skills/<name>/SKILL.md
```
Define a skill you can invoke in the REPL with `/name` or via the `skill` tool.

```text
.ci2lab/mcp.json
```
Configure MCP servers; their tools appear as `mcp__<server>__<tool>`.

```text
CI2LAB.md
AGENTS.md
```
Persistent instructions injected into the system prompt (project memory).

## Run logging

```powershell
ci2lab --workspace . "list the files"
```
Save a normal run under `runs/`.

```powershell
ci2lab --no-log "list the files"
```
Disable logging for that run.

```powershell
ci2lab --runs-dir ./_runs "hello"
```
Save artifacts under `./_runs`.

```powershell
$env:CI2LAB_NO_LOG="1"
```
Disable logs via environment variable.

```powershell
$env:CI2LAB_RUNS_DIR="./_runs"
```
Set the logs folder via environment variable.

## Configuration via environment variables

```powershell
$env:CI2LAB_MODEL="llama3.1:8b"
```
Set the default model.

```powershell
$env:CI2LAB_OLLAMA_URL="http://localhost:11434"
```
Set the Ollama base URL.

```powershell
$env:CI2LAB_BACKEND_URL="http://localhost:11434/v1"
```
Set the OpenAI-compatible endpoint.

```powershell
$env:CI2LAB_TOOL_MODE="native"
```
Set the tool mode.

```powershell
$env:CI2LAB_MAX_ROUNDS="25"
```
Set the maximum number of rounds.

```powershell
$env:CI2LAB_WORKSPACE="."
```
Set the default workspace.

```powershell
$env:CI2LAB_CWD="."
```
Legacy alias for the workspace.

```powershell
$env:CI2LAB_STREAM="false"
```
Disable streaming by default.

```powershell
$env:CI2LAB_AUTO_CONFIRM="1"
```
Enable auto-confirmation.

```powershell
$env:CI2LAB_YES="1"
```
Enable auto-confirmation.

```powershell
$env:CI2LAB_CONFIG="./ci2lab.yaml"
```
Force the config file path.

```powershell
$env:CI2LAB_WRITE_TOOLS_ENABLED="false"
```
Disable `write_file` and `edit_file`.

```powershell
$env:CI2LAB_REQUIRE_DIFF_PREVIEW="false"
```
Allow skipping the mandatory edit preview.

## Configuration via file

Create `ci2lab.yaml` at the project root or `~/.ci2lab/ci2lab.yaml`.

```yaml
model: llama3.1:8b
runs_dir: runs
log_runs: true
```
Configure the model and logging.

```yaml
workspace: .
max_rounds: 25
stream: true
auto_confirm: false
```
Configure the workspace and agent behavior.

```yaml
backend_url: http://localhost:11434/v1
tool_mode: native
```
Configure the endpoint and tool mode.

```yaml
write_tools_enabled: false
```
Disable the write tools.

```yaml
require_diff_preview: true
```
Keep the diff preview mandatory before editing.

```yaml
no_log: true
```
Disable logging from YAML.

## The agent's internal tools

The model invokes these during a task (28 built-in tools + dynamic MCP). See `docs/TOOLS_ROADMAP.md`.

**Reading / exploration:** `ls`, `read_file`, `read_document`, `grep`, `glob`, `file_info`, `tree`, `inspect_file`

**Writing / conversion:** `write_file`, `edit_file`, `write_docx`, `apply_patch`, `fill_docx_template`, `docx_to_pdf`, `pdf_to_docx`, `notebook_edit`

**Shell / git:** `bash`, `git_status`, `git_diff`

**Workflow / integrations:** `todo_write`, `ask_user`, `web_search`, `web_fetch`, `skill`, `mcp_call`, `mcp__*`

## Included eval tasks

```text
001_list_files
```
Checks the use of `ls`.

```text
002_read_file
```
Checks the use of `read_file`.

```text
003_find_function
```
Checks searching with `grep` or `glob` plus `read_file`.

```text
004_block_dangerous_bash
```
Checks that dangerous commands are blocked.

```text
005_edit_file_denied
```
Checks supervised editing when denied.

```text
006_edit_file_approved
```
Checks supervised editing when approved.

```text
007_write_tools_disabled
```
Checks that writing is blocked by configuration.

## Recommended quick sequence

```powershell
cd IAmultiagentica
```
Enter the project.

```powershell
py -m venv .venv
```
Create the virtual environment.

```powershell
.\.venv\Scripts\Activate.ps1
```
Activate the virtual environment.

```powershell
pip install -e ".[dev]"
```
Install the dependencies.

```powershell
irm https://ollama.com/install.ps1 | iex
```
Install Ollama on Windows.

```powershell
ollama --version
```
Check that Ollama is installed.

```powershell
ci2lab doctor
```
Check the environment.

```powershell
ci2lab hardware
```
Detect your machine's capacity.

```powershell
ci2lab models recommend "program in Python"
```
Pick a model for your case.

```powershell
ci2lab models install <MODEL_ID>
```
Get the install command for the model.

```powershell
ollama pull <OLLAMA_TAG>
```
Download the model in Ollama.

```powershell
ci2lab --model <MODEL_ID> chat
```
Open an agent chat with that model.
