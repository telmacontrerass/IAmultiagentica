"""Ask the user a question during agent execution."""

from __future__ import annotations


def ask_user(question: str, options: list[str] | None = None) -> str:
    if not question or not str(question).strip():
        return "Error: question is required"

    q = str(question).strip()
    print()  # noqa: T201 — intentional user-facing prompt
    print(q)  # noqa: T201

    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if opts:
        for i, opt in enumerate(opts, start=1):
            print(f"  {i}. {opt}")  # noqa: T201
        print("(Enter a number or free text)")  # noqa: T201

    try:
        answer = input("> ").strip()  # noqa: T201
    except EOFError:
        return "Error: no user input (session ended)"

    if not answer:
        return "Error: empty answer"

    if opts and answer.isdigit():
        idx = int(answer)
        if 1 <= idx <= len(opts):
            return opts[idx - 1]

    return answer
