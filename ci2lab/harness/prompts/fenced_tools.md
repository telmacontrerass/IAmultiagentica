## Tool format (text mode)

This model calls tools by writing a fenced code block whose **language tag is the tool name**. The system finds that block, runs the tool, and shows you the result. Then you continue.

Hard rules:

- The opening fence must be the tool name, e.g. ` ```write_file `. Do NOT use ` ```python ` for actions.
- ` ```json ` with `{"name": "write_file", "arguments": {...}}` is also accepted as a fallback.
- Never put `write_file` inside a ` ```bash ` block. Bash is only for shell commands like `python wordle.py`.
- Use one tool block at a time, then wait for the result before the next step.
- After a tool runs, only say the task is done if the result confirms success.

### Tools that take a single value

The body of the block is the value itself (no JSON).

List a directory:

```ls
.
```

Read a text file or PDF with extractable text (one path per block):

```read_file
src/main.py
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

### edit_file (replace exact text in an existing file)

The body MUST be a single JSON object with `path`, `old_string`, and `new_string`. `old_string` must match the existing text exactly.

```edit_file
{"path": "src/main.py", "old_string": "DEBUG = True", "new_string": "DEBUG = False"}
```

File metadata (path in block):

```file_info
src/main.py
```

Directory tree (optional JSON for depth/limits):

```tree
{"path": ".", "depth": 2, "max_entries": 100}
```

Inspect a line range from a text file:

```inspect_file
{"path": "src/main.py", "start": 1, "end": 40}
```

Available tools: `bash`, `read_file`, `ls`, `grep`, `glob`, `write_file`, `edit_file`, `file_info`, `tree`, `inspect_file`.
