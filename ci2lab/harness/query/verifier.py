"""Opt-in completion verification.

After the agent reports a task as done and effectful work actually happened this
turn, a fresh read-only subagent independently checks the workspace against the
ORIGINAL user request. The agent grades its own homework against its own summary;
this grades it against reality. On a clear failure the verifier returns concrete
gaps, which the loop feeds back so the agent fixes them before truly finishing.

Kept deliberately conservative: the verifier is told to lean PASS when unsure,
and only a first line that says FAIL counts as a failure — weak local models that
ramble are treated as a pass rather than stalling the task forever.
"""

from __future__ import annotations

from dataclasses import replace

from ci2lab.contracts.types import ModelSelection
from ci2lab.harness.token_usage import TokenUsageState
from ci2lab.harness.types import AgentConfig

# Cap how many times verification may run per turn so a stubborn verifier cannot
# loop the task forever.
VERIFIER_MAX_PER_TURN = 2

_VERIFIER_TASK = (
    "You are independently verifying whether another agent fully completed the "
    "user's request. Do not trust its summary — check the real workspace.\n\n"
    "Original user request:\n"
    "<request>\n{request}\n</request>\n\n"
    "What the agent reports doing this turn:\n"
    "<actions>\n{actions}\n</actions>\n\n"
    "Use your read-only tools to inspect the ACTUAL result (open the files it "
    "claims to have written/edited, confirm the requested content is really "
    "there). Judge only against the request.\n\n"
    "Reply in this exact format:\n"
    "- First line: `PASS` if every part of the request is genuinely done, "
    "otherwise `FAIL`.\n"
    "- If FAIL, add a short bullet list of the specific, verifiable gaps that "
    "must be fixed. List only real problems you confirmed; if you are unsure, "
    "lean PASS."
)


def _verdict_is_failure(output: str) -> bool:
    """Return ``True`` only when the verifier's first line is a clear FAIL."""
    text = (output or "").strip()
    if not text:
        return False  # no verdict -> do not block the task
    first_line = text.splitlines()[0].strip().upper()
    # Only a clear FAIL on the first line counts; "PASS" anywhere on that line
    # wins ties so an explained pass is never read as a failure.
    return "FAIL" in first_line and "PASS" not in first_line


def verify_completion(
    config: AgentConfig,
    selection: ModelSelection,
    user_prompt: str,
    actions: list[str],
) -> str | None:
    """Independently verify task completion with a fresh read-only subagent.

    Spawns a reviewer subagent that inspects the real workspace against the
    original request, using isolated token accounting. Deliberately
    conservative: leans toward passing when the verdict is unclear or the
    verifier could not run.

    Args:
        config: The active agent configuration (cloned with fresh token usage
            for the subagent).
        selection: The resolved model selection for the verifier subagent.
        user_prompt: The original user request to verify against.
        actions: Human-readable descriptions of what the agent reports doing
            this turn.

    Returns:
        The trimmed verifier output describing concrete gaps to fix when the
        work clearly fails verification, or ``None`` when it passes, the
        selection is missing, or the verifier could not run.
    """
    if selection is None:
        return None

    from ci2lab.harness.multiagent.runner import run_subagent
    from ci2lab.harness.multiagent.state import AgentRole

    actions_text = "\n".join(f"- {a}" for a in actions) if actions else "- (none recorded)"
    task = _VERIFIER_TASK.format(request=user_prompt.strip(), actions=actions_text)

    # Isolated token accounting; a fresh read-only reviewer subagent.
    parent_for_sub = replace(config, token_usage=TokenUsageState())
    result = run_subagent(
        AgentRole.REVIEWER,
        task,
        selection,
        parent_for_sub,
        capture_output=True,
    )

    if result.status != "completed":
        # If the verifier itself could not run, do not block the user's task.
        return None
    if _verdict_is_failure(result.output):
        return result.output.strip()
    return None
