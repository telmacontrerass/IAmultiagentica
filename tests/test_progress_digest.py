"""Tests for the automatic progress digest (persistent working memory)."""

from ci2lab.harness.context.progress import PROGRESS_HEADER, progress_digest
from ci2lab.harness.grounding_review.evidence import EvidenceLedger


def _ledger(*records):
    ledger = EvidenceLedger(user_prompt="do the task")
    for tool, args, content, ok in records:
        ledger.add(tool, args, content, ok=ok)
    return ledger


def test_empty_ledger_yields_no_digest():
    assert progress_digest(EvidenceLedger(user_prompt="x")) == ""


def test_digest_lists_writes_commands_and_reads():
    ledger = _ledger(
        ("read_file", {"path": "a.py"}, "contents", True),
        ("write_file", {"path": "a.py"}, "ok", True),
        ("bash", {"command": "pytest -q"}, "3 passed", True),
    )
    digest = progress_digest(ledger)
    assert PROGRESS_HEADER in digest
    assert "Wrote/edited: a.py" in digest
    assert "Ran: pytest -q" in digest
    assert "Inspected: a.py" in digest


def test_digest_dedupes_repeated_paths():
    ledger = _ledger(
        ("write_file", {"path": "a.py"}, "ok", True),
        ("write_file", {"path": "a.py"}, "ok", True),
        ("write_file", {"path": "b.py"}, "ok", True),
    )
    digest = progress_digest(ledger)
    # a.py appears once despite two writes.
    assert digest.count("a.py") == 1
    assert "b.py" in digest


def test_digest_surfaces_only_most_recent_failure():
    ledger = _ledger(
        ("bash", {"command": "make"}, "error: first failure", False),
        ("bash", {"command": "make test"}, "error: second failure", False),
    )
    digest = progress_digest(ledger)
    assert "second failure" in digest
    assert "first failure" not in digest


def test_successful_writes_are_not_treated_as_failures():
    ledger = _ledger(("write_file", {"path": "a.py"}, "ok", True))
    digest = progress_digest(ledger)
    assert "failure" not in digest.lower()


def test_long_command_is_truncated():
    long_cmd = "python " + "x" * 200
    ledger = _ledger(("bash", {"command": long_cmd}, "ok", True))
    digest = progress_digest(ledger)
    assert "…" in digest
    # The digest line stays compact rather than echoing the whole command.
    assert len(digest) < len(long_cmd)
