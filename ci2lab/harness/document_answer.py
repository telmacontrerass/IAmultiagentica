"""Deterministic answers for simple document-reading requests.

Small local models can be unreliable after a long tool result. For direct
document requests ("lee", "resume", "ideas principales"), this module provides
an extractive fallback based only on the text returned by read_document.
"""

from __future__ import annotations

import re

_PAGE_MARKER_RE = re.compile(r"^\[PDF page \d+/\d+\]$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def maybe_answer_document_request(
    user_prompt: str,
    document_outputs: list[str],
) -> str | None:
    if not document_outputs or not _is_simple_document_answer_request(user_prompt):
        return None

    document_text = "\n\n".join(document_outputs)
    title, body = _split_document_output(document_text)
    lines = _content_lines(body)
    if not lines:
        return None

    bullets = _extract_bullets(lines, max_items=6)
    if not bullets:
        return None

    heading = title or _document_name(document_text) or "documento"
    intro = f"He leído {heading}. Estas son las ideas principales:"
    return intro + "\n\n" + "\n".join(f"- {bullet}" for bullet in bullets)


def _is_simple_document_answer_request(user_prompt: str) -> bool:
    text = user_prompt.lower()
    read_markers = (
        "lee",
        "leer",
        "resume",
        "resumir",
        "resumen",
        "ideas principales",
        "puntos principales",
        "contenido",
        "de que trata",
        "de qué trata",
        "analiza",
        "analizar",
    )
    return any(marker in text for marker in read_markers)


def _split_document_output(document_text: str) -> tuple[str | None, str]:
    name = _document_name(document_text)
    marker = "Texto extraido:"
    if marker in document_text:
        _, _, body = document_text.partition(marker)
    else:
        body = document_text

    lines = _content_lines(body)
    title = _first_title_line(lines) or name
    return title, body


def _document_name(document_text: str) -> str | None:
    for line in document_text.splitlines():
        if line.startswith("Documento:"):
            value = line.partition(":")[2].strip()
            return value or None
    return None


def _content_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        if _PAGE_MARKER_RE.match(line):
            continue
        if line.startswith(("Documento:", "Tipo:", "Paginas/secciones:", "Texto extraido:")):
            continue
        lines.append(line)
    return lines


def _first_title_line(lines: list[str]) -> str | None:
    for line in lines[:8]:
        plain = line.strip(":")
        words = plain.split()
        if 2 <= len(words) <= 12 and plain.upper() == plain:
            return plain.title()
    return None


def _extract_bullets(lines: list[str], *, max_items: int) -> list[str]:
    candidates = _paragraph_candidates(lines)
    if not candidates:
        return []

    scored = [(score, index, text) for index, (score, text) in enumerate(candidates)]
    scored.sort(key=lambda item: (-item[0], item[1]))

    chosen: list[str] = []
    for _, _, text in scored:
        normalized = _clean_sentence(text)
        if not normalized or _is_duplicate(normalized, chosen):
            continue
        chosen.append(normalized)
        if len(chosen) >= max_items:
            break
    return chosen


def _paragraph_candidates(lines: list[str]) -> list[tuple[int, str]]:
    joined = " ".join(lines)
    sentences = [
        part.strip()
        for part in _SENTENCE_RE.split(joined)
        if 35 <= len(part.strip()) <= 260
    ]
    if not sentences:
        sentences = [line for line in lines if 20 <= len(line) <= 220]

    keywords = _top_keywords(lines)
    candidates: list[tuple[int, str]] = []
    for sentence in sentences:
        low = sentence.lower()
        score = sum(2 for keyword in keywords if keyword in low)
        score += sum(
            1
            for marker in (
                "formal",
                "informal",
                "academic",
                "writing",
                "register",
                "passive",
                "voice",
                "example",
                "exercise",
                "table",
                "equivalent",
            )
            if marker in low
        )
        candidates.append((score, sentence))
    return candidates


def _top_keywords(lines: list[str]) -> list[str]:
    stop = {
        "about",
        "above",
        "after",
        "also",
        "and",
        "are",
        "because",
        "below",
        "como",
        "con",
        "del",
        "does",
        "for",
        "from",
        "have",
        "into",
        "las",
        "los",
        "more",
        "para",
        "que",
        "the",
        "this",
        "una",
        "use",
        "uses",
        "with",
        "you",
    }
    counts: dict[str, int] = {}
    for line in lines:
        for word in re.findall(r"[A-Za-zÀ-ÿ]{4,}", line.lower()):
            if word in stop:
                continue
            counts[word] = counts.get(word, 0) + 1
    return [
        word
        for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]


def _clean_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip(" -")


def _is_duplicate(candidate: str, chosen: list[str]) -> bool:
    cand_words = set(re.findall(r"[A-Za-zÀ-ÿ]{4,}", candidate.lower()))
    if not cand_words:
        return False
    for item in chosen:
        item_words = set(re.findall(r"[A-Za-zÀ-ÿ]{4,}", item.lower()))
        if item_words and len(cand_words & item_words) / len(cand_words) > 0.75:
            return True
    return False
