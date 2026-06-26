"""Turn a raw manuscript into an addressable, verifiable source of truth.

The scientific peer-review flow must never invent claims about a paper. The
foundation of that guarantee is this module: it takes the raw extracted text of
a manuscript and produces a *segmented, anchored, normalized* index.

* Reviewers are shown the anchored text and may only cite ``[A12]``-style
  anchors that come from it.
* A deterministic verifier (``grounding.py``) checks every quoted span against
  the same normalized segments, so a fabricated quote physically fails the gate.

This module is intentionally pure (no I/O, no model calls) so the groundedness
core can be unit-tested exhaustively.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

# Default cap on how much anchored text we inject into a reviewer prompt. The
# full segment list is always kept for verification; only the *shown* text is
# capped, and truncation is reported so the review never silently hides content.
DEFAULT_ANCHORED_CHAR_BUDGET = 60_000

# Segments longer than this are split further so anchors stay fine-grained
# enough to be a useful citation target.
MAX_SEGMENT_CHARS = 1_400

# A quote must contribute at least this many normalized characters to be
# checkable. Very short fragments match by accident and are not real evidence.
MIN_QUOTE_MATCH_CHARS = 16

# Fraction of a quote that must appear as one contiguous run in the manuscript
# for a fuzzy (non-exact) match to count. High on purpose: an invented quote
# shares no long contiguous run with the real text.
FUZZY_COVERAGE_THRESHOLD = 0.9


@dataclass(frozen=True)
class Segment:
    """One addressable unit of the manuscript."""

    anchor: str
    display: str
    norm: str
    norm_start: int  # offset of this segment's norm inside the index full_norm


@dataclass(frozen=True)
class QuoteMatch:
    """Result of checking one quoted span against the manuscript."""

    found: bool
    anchor: str | None
    coverage: float
    exact: bool


@dataclass(frozen=True)
class ManuscriptIndex:
    """A manuscript prepared for grounded review."""

    segments: tuple[Segment, ...]
    anchored_text: str
    full_norm: str
    segment_count: int
    shown_segment_count: int
    truncated: bool

    @property
    def readable(self) -> bool:
        """Whether the manuscript yielded at least one usable segment."""
        return self.segment_count > 0

    def segment_for(self, anchor: str) -> Segment | None:
        """Return the segment carrying ``anchor``, or ``None`` if absent.

        Args:
            anchor: An anchor label (e.g. ``"A12"``); canonicalized before lookup.

        Returns:
            The matching :class:`Segment`, or ``None`` when no segment uses it.
        """
        anchor = _canonical_anchor(anchor)
        for segment in self.segments:
            if segment.anchor == anchor:
                return segment
        return None


def strip_accents(text: str) -> str:
    """Return ``text`` with combining accent marks removed (NFKD-decomposed)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_for_match(text: str) -> str:
    """Reduce text to a comparison form: accent-free, lowercase, alnum+space.

    Both the manuscript and any quoted span pass through this, so punctuation,
    casing, accents, and OCR whitespace noise cannot cause a real quote to be
    rejected — while invented text still fails to match.
    """
    text = strip_accents(str(text or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _collapse_ws(text: str) -> str:
    """Collapse runs of whitespace in ``text`` to single spaces and strip ends."""
    return re.sub(r"\s+", " ", text).strip()


def _dehyphenate(raw: str) -> str:
    """Join words split across a line break: ``"exam-\\nple"`` -> ``"example"``."""
    # Join words split across a line break: "exam-\nple" -> "example".
    return re.sub(r"-\s*\n\s*", "", raw)


def _split_paragraphs(raw: str) -> list[str]:
    """Split raw text into paragraph strings, falling back to lines/word chunks."""
    cleaned = _dehyphenate(raw)
    parts = re.split(r"\n\s*\n", cleaned)
    paragraphs = [_collapse_ws(part) for part in parts]
    paragraphs = [part for part in paragraphs if part]
    # A PDF dumped as one blob (no blank lines) yields a single huge paragraph;
    # fall back to line splitting, then to word-window chunking.
    if len(paragraphs) <= 1 and cleaned.strip():
        line_parts = [_collapse_ws(line) for line in cleaned.splitlines()]
        line_parts = [line for line in line_parts if line]
        if len(line_parts) > 1:
            paragraphs = line_parts
        else:
            paragraphs = _chunk_words(_collapse_ws(cleaned))
    return paragraphs


def _chunk_words(text: str, words_per_chunk: int = 90) -> list[str]:
    """Split ``text`` into chunks of at most ``words_per_chunk`` words each."""
    words = text.split()
    if not words:
        return []
    return [" ".join(words[i : i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]


def _split_long_segment(text: str) -> list[str]:
    """Split a long segment at sentence boundaries (then word chunks) to fit the cap."""
    if len(text) <= MAX_SEGMENT_CHARS:
        return [text]
    # Prefer sentence boundaries; fall back to word chunks.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= MAX_SEGMENT_CHARS:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    expanded: list[str] = []
    for chunk in chunks:
        if len(chunk) <= MAX_SEGMENT_CHARS:
            expanded.append(chunk)
        else:
            expanded.extend(_chunk_words(chunk))
    return expanded or [text[:MAX_SEGMENT_CHARS]]


def _canonical_anchor(anchor: str) -> str:
    """Normalize an anchor label to canonical ``A<n>`` form (e.g. ``"a012"`` -> ``"A12"``)."""
    raw = str(anchor or "").strip().upper()
    match = re.search(r"A?\s*0*(\d+)", raw)
    if not match:
        return raw
    return f"A{int(match.group(1))}"


def build_index(
    raw_text: str,
    *,
    anchored_char_budget: int = DEFAULT_ANCHORED_CHAR_BUDGET,
) -> ManuscriptIndex:
    """Segment, anchor, and normalize a manuscript for grounded review.

    Args:
        raw_text: The raw extracted manuscript text.
        anchored_char_budget: Maximum number of characters of anchored text to
            include in the shown ``anchored_text`` (the full segment list is
            always retained for verification).

    Returns:
        A :class:`ManuscriptIndex` with segmented, anchored, and normalized text.
    """
    paragraphs: list[str] = []
    for paragraph in _split_paragraphs(raw_text or ""):
        paragraphs.extend(_split_long_segment(paragraph))

    segments: list[Segment] = []
    norm_parts: list[str] = []
    cursor = 0
    for index, display in enumerate(paragraphs, start=1):
        norm = normalize_for_match(display)
        if not norm:
            continue
        anchor = f"A{index}"
        segments.append(Segment(anchor=anchor, display=display, norm=norm, norm_start=cursor))
        norm_parts.append(norm)
        cursor += len(norm) + 1  # +1 for the space joiner used in full_norm

    full_norm = " ".join(norm_parts)

    anchored_chunks: list[str] = []
    used = 0
    shown = 0
    truncated = False
    for segment in segments:
        block = f"[{segment.anchor}] {segment.display}"
        if anchored_chunks and used + len(block) + 2 > anchored_char_budget:
            truncated = True
            break
        anchored_chunks.append(block)
        used += len(block) + 2
        shown += 1

    return ManuscriptIndex(
        segments=tuple(segments),
        anchored_text="\n\n".join(anchored_chunks),
        full_norm=full_norm,
        segment_count=len(segments),
        shown_segment_count=shown,
        truncated=truncated,
    )


def _anchor_at_offset(index: ManuscriptIndex, offset: int) -> str | None:
    """Return the anchor of the segment that contains ``offset`` in ``full_norm``."""
    chosen: str | None = None
    for segment in index.segments:
        if segment.norm_start <= offset:
            chosen = segment.anchor
        else:
            break
    return chosen


def find_quote(index: ManuscriptIndex, quote: str) -> QuoteMatch:
    """Locate a quoted span in the manuscript by normalized, fuzzy matching.

    Returns ``found=False`` for anything that is not genuinely present — this is
    the deterministic anti-hallucination gate, not a courtesy check.
    """
    quote_norm = normalize_for_match(quote)
    if len(quote_norm) < MIN_QUOTE_MATCH_CHARS:
        return QuoteMatch(found=False, anchor=None, coverage=0.0, exact=False)
    if not index.full_norm:
        return QuoteMatch(found=False, anchor=None, coverage=0.0, exact=False)

    # 1. Exact normalized containment (handles spans across segment joins too).
    offset = index.full_norm.find(quote_norm)
    if offset != -1:
        return QuoteMatch(
            found=True,
            anchor=_anchor_at_offset(index, offset),
            coverage=1.0,
            exact=True,
        )

    # 2. Fuzzy: require one long contiguous run of the quote inside the text.
    matcher = SequenceMatcher(None, index.full_norm, quote_norm, autojunk=False)
    block = matcher.find_longest_match(0, len(index.full_norm), 0, len(quote_norm))
    coverage = block.size / len(quote_norm) if quote_norm else 0.0
    if coverage >= FUZZY_COVERAGE_THRESHOLD:
        return QuoteMatch(
            found=True,
            anchor=_anchor_at_offset(index, block.a),
            coverage=round(coverage, 3),
            exact=False,
        )
    return QuoteMatch(found=False, anchor=None, coverage=round(coverage, 3), exact=False)


def term_present(index: ManuscriptIndex, term: str) -> bool:
    """True if a (normalized) term/phrase occurs anywhere in the manuscript.

    Used to refute 'X is missing' claims: if the term is actually present, the
    absence claim is false and must be dropped.
    """
    term_norm = normalize_for_match(term)
    if not term_norm:
        return False
    return term_norm in index.full_norm
