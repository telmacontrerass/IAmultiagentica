## Tool format (text mode)

You call a tool by writing ONE fenced code block whose **language tag is the tool name**. The system runs that block and returns the result; then you continue.

Hard rules (read carefully — breaking these means the tool does NOT run):

- The opening fence must be the exact tool name, e.g. ` ```write_file `. Never use ` ```python ` or ` ```text ` for an action.
- Output exactly ONE tool block per message, then stop and wait for the result.
- Do not describe a tool call in prose or in a plain ` ```json ` block of explanation — only a real tool-named block runs. (` ```json ` with `{"name": "...", "arguments": {...}}` is accepted only as a fallback.)
- Never put `read_file`, `edit_file`, `write_file`, or other tools inside a ` ```bash ` block. `bash` is only for real shell commands like `python wordle.py`.
- To read a file use ` ```read_file ` with the path as the body, not ` ```bash\nread_file Pruebas.py `.
- Use the exact argument names shown below.
- Only say the task is done after a tool result confirms success.

### Tools that take a single value

The body of the block is the value itself (no JSON).

List a directory:

```ls
.
```

Read a text/code file with numbered lines (one path per block):

```read_file
Pruebas.py
```

Read a document by format (PDF, DOCX, PPTX, XLSX, CSV, Markdown, plain text):

```read_document
rubrica.docx
```

Find files by glob pattern:

```glob
**/*.py
```

Run a shell command:

```bash
python -m pytest tests/ -q
```

### grep

Either a bare pattern:

```grep
def main
```

...or JSON when you need options:

```grep
{"pattern": "def main", "glob": "*.py", "ignore_case": true}
```

### write_file (create or overwrite a file)

Use `write_file` when the user explicitly asks to create or save a file in the project. Security blocks external paths and sensitive files (`.env`, keys, credentials); it does **not** forbid normal file creation inside the workspace.

The body MUST be a single JSON object with `path` and `content`. Put the full file text in `content` (escape newlines as `\n`). The key is `content`, never `new_string`.

```write_file
{"path": "count_to_100.py", "content": "for i in range(1, 101):\n    print(i)\n"}
```

User-requested doc example:

```write_file
{"path": "docs/resumen.md", "content": "# Resumen\n\nContenido pedido por el usuario.\n"}
```

Do not create error/log files (e.g. `ci2lab_error.txt`) on your own after a tool block unless the user asked for that file.

### write_docx (create or overwrite a Word document)

Use for `.docx` files. The body is markdown; pandoc converts it to Word.

```write_docx
{"path": "informe.docx", "content": "# Título\n\nPárrafo del documento.\n"}
```

### docx_to_pdf (convert Word to PDF)

Convert a `.docx` file to PDF. Tries LibreOffice first (best for non-Latin text), then pandoc with a Unicode-capable engine. Pass the existing `.docx` path as `source`; do not pass a glob pattern.

```docx_to_pdf
{"source": "informe.docx", "output": "informe.pdf"}
```

### pdf_to_docx (convert PDF to Word)

Convert a `.pdf` file to a `.docx` file using pdf2docx. Preserves layout, images, and tables.

```pdf_to_docx
{"source": "documento.pdf", "output": "documento.docx"}
```

### edit_file (replace exact text in an existing file)

The body MUST be a single JSON object with `path`, `old_string`, and `new_string`. `old_string` must match the existing text exactly.

```edit_file
{"path": "Pruebas.py", "old_string": "linea tres", "new_string": "Linea cambiada otra vez"}
```

### apply_patch (unified diff)

The body is the patch text itself (or JSON with a `patch` field). Use after `read_file` when a multi-line change is easier as a diff.

```apply_patch
--- a/Pruebas.py
+++ b/Pruebas.py
@@ -1,4 +1,4 @@
 # archivo de prueba
 linea dos
-linea tres
+Linea cambiada otra vez
 linea cuatro
```

### file_info

Path metadata without reading full content:

```file_info
Pruebas.py
```

### tree

Directory tree (optional JSON for depth/limits):

```tree
{"path": ".", "depth": 2, "max_entries": 100}
```

### inspect_file

Inspect a line range from a text file:

```inspect_file
{"path": "Pruebas.py", "start": 1, "end": 4}
```

### todo_write

```todo_write
{"todos": [{"id": "1", "content": "Create snake.py", "status": "in_progress"}, {"id": "2", "content": "Run tests", "status": "pending"}]}
```

### ask_user

```ask_user
{"question": "Which Python version should I target?", "options": ["3.11", "3.12"]}
```

### web_fetch

```web_fetch
https://docs.python.org/3/library/random.html
```

### web_search

Use this when the user asks for live/current info and did not provide a URL:

```web_search
{"query": "Spain vs Cape Verde latest result", "max_results": 5}
```

Then fetch selected sources with `web_fetch`.

### notebook_edit

```notebook_edit
{"path": "analysis.ipynb", "cell_index": 0, "new_source": "import pandas as pd\n", "cell_type": "code"}
```

### git_status / git_diff

```git_status
.
```

```git_diff
{"path": "src/main.py", "staged": false}
```

### skill

```skill
{"skill_name": "make-word-doc", "args": "report about Q1 sales"}
```

### mcp_call (fallback when no dedicated mcp__ tool is listed)

```mcp_call
{"server": "my-server", "tool": "search", "arguments": {"query": "docs"}}
```

Available tools: `bash`, `read_document`, `read_file`, `ls`, `grep`, `glob`, `write_file`, `write_docx`, `docx_to_pdf`, `pdf_to_docx`, `edit_file`, `apply_patch`, `file_info`, `tree`, `inspect_file`, `notebook_edit`, `todo_write`, `ask_user`, `web_search`, `web_fetch`, `git_status`, `git_diff`, `skill`, `mcp_call`, plus any `mcp__*` tools listed in the system prompt.
