"""Context window management: trim, compaction, and the progress digest."""

from ci2lab.harness.context.compact import manage_context, micro_compact, summarize_history
from ci2lab.harness.context.progress import progress_digest
from ci2lab.harness.context.trim import estimate_tokens, trim_messages

__all__ = [
    "estimate_tokens",
    "manage_context",
    "micro_compact",
    "progress_digest",
    "summarize_history",
    "trim_messages",
]
