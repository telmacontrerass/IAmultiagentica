"""Ask the user a question during agent execution."""

from __future__ import annotations

from ci2lab.harness.terminal_input import read_prompt_line


def ask_user(question: str, options: list[str] | None = None) -> str:
    """Prompt the user for input mid-execution and return their answer.

    The question is printed, followed by any numbered options, and a single line
    is read from the terminal. When options are supplied and the user enters a
    valid number, the corresponding option text is returned; otherwise the raw
    free-text answer is returned.

    Args:
        question: The question to display. Required; whitespace-only is rejected.
        options: Optional choices to display as a numbered list. Blank entries
            are ignored.

    Returns:
        The selected option text, the user's free-text answer, or a
        human-readable ``Error:`` string when the question is missing, the
        session has ended, or the answer is empty.
    """
    if not question or not str(question).strip():
        return "Error: question is required"

    q = str(question).strip()
    print()
    print(q)

    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if opts:
        for i, opt in enumerate(opts, start=1):
            print(f"  {i}. {opt}")
        print("(Enter a number or free text)")

    try:
        answer = read_prompt_line("> ")
    except EOFError:
        return "Error: no user input (session ended)"

    if not answer:
        return "Error: empty answer"

    if opts and answer.isdigit():
        idx = int(answer)
        if 1 <= idx <= len(opts):
            return opts[idx - 1]

    return answer
