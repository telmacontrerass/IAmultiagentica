## Tool format (text mode)

This model calls tools by writing a fenced code block whose **language tag is the tool name**. The system finds that block, runs the tool, and shows you the result. Then you continue.

Hard rules:

- The opening fence must be the tool name, e.g. ` ```write_file `. Do NOT use ` ```json `, ` ```python `, or ` ```sh ` — those are treated as plain text and will NOT run.
- Use one tool block at a time, then wait for the result before the next step.
- After a tool runs, only say the task is done if the result confirms success.

### Tools that take a single value

The body of the block is the value itself (no JSON).

List a directory:

```ls
.
```

Read a file (one path per block):

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

The body MUST be a single JSON object with `path` and `content`. Put the full file text in `content` (escape newlines as `\n`). The key is `content`, never `new_string`.

```write_file
{"path": "count_to_100.py", "content": "for i in range(1, 101):\n    print(i)\n"}
```

### edit_file (replace exact text in an existing file)

The body MUST be a single JSON object with `path`, `old_string`, and `new_string`. `old_string` must match the existing text exactly.

```edit_file
{"path": "src/main.py", "old_string": "DEBUG = True", "new_string": "DEBUG = False"}
```

Available tools: `bash`, `read_file`, `ls`, `grep`, `glob`, `write_file`, `edit_file`.
