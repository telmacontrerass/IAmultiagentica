"""Multiple-choice quiz generation from local documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ci2lab.harness.tools.filesystem_parts.access import resolve_or_error
from ci2lab.harness.tools.filesystem_parts.documents import extract_document_text
from ci2lab.harness.tools.secret_files import is_sensitive_path, secret_file_block_message

DEFAULT_OPTIONS_PER_QUESTION = 4
MAX_QUESTIONS = 50
MAX_OPTIONS_PER_QUESTION = 8
MIN_OPTIONS_PER_QUESTION = 2

_DIFFICULTY_ALIASES = {
    "basic": "basic",
    "basico": "basic",
    "básico": "basic",
    "easy": "basic",
    "facil": "basic",
    "fácil": "basic",
    "medio": "medium",
    "media": "medium",
    "medium": "medium",
    "intermedio": "medium",
    "dificil": "hard",
    "difícil": "hard",
    "hard": "hard",
    "avanzado": "hard",
}

_STOPWORDS = {
    "ademas",
    "además",
    "also",
    "ante",
    "aunque",
    "because",
    "como",
    "con",
    "cuando",
    "desde",
    "during",
    "entre",
    "esta",
    "este",
    "estos",
    "for",
    "from",
    "however",
    "las",
    "los",
    "para",
    "pero",
    "porque",
    "que",
    "segun",
    "según",
    "sin",
    "sobre",
    "that",
    "the",
    "their",
    "this",
    "una",
    "with",
}


@dataclass(frozen=True)
class _Fact:
    sentence: str
    answer: str
    stem: str


def create_quiz_questions(
    cwd: str,
    path: str,
    question_count: int,
    difficulty: str,
    options_per_question: int = DEFAULT_OPTIONS_PER_QUESTION,
) -> str:
    """Create multiple-choice questions from a supported document.

    Args:
        cwd: Workspace root used to resolve ``path``.
        path: Document path, relative to ``cwd`` or absolute inside it.
        question_count: Number of questions to create.
        difficulty: ``basic``, ``medium`` or ``hard`` (Spanish aliases accepted).
        options_per_question: Number of choices per question. Defaults to four.

    Returns:
        A Markdown quiz with exactly one correct answer marked per question, or
        an ``"Error: ..."`` message when validation or extraction fails.
    """
    resolved, err = resolve_or_error(path, cwd)
    if err:
        return err
    assert resolved is not None
    if not resolved.is_file():
        return f"Error: file does not exist: {resolved}"
    if is_sensitive_path(resolved):
        return secret_file_block_message()

    question_count, err = _validate_int(
        question_count,
        name="question_count",
        minimum=1,
        maximum=MAX_QUESTIONS,
    )
    if err:
        return err
    options_per_question, err = _validate_int(
        options_per_question,
        name="options_per_question",
        minimum=MIN_OPTIONS_PER_QUESTION,
        maximum=MAX_OPTIONS_PER_QUESTION,
    )
    if err:
        return err

    difficulty_key = _normalize_difficulty(difficulty)
    if difficulty_key is None:
        return "Error: difficulty must be one of basic, medium or hard"

    text = extract_document_text(resolved, include_metadata=False)
    if text.startswith("Error:"):
        return text
    facts = _extract_facts(text, difficulty_key)
    if len(facts) < question_count:
        return (
            "Error: not enough extractable facts to create "
            f"{question_count} questions; found {len(facts)}"
        )

    questions = []
    answer_key = []
    for index, fact in enumerate(facts[:question_count], start=1):
        options = _build_options(fact.answer, facts, index - 1, options_per_question)
        questions.append(_render_question(index, fact, options, difficulty_key))
        answer_key.append(_render_answer_key_entry(index, options))

    label = {"basic": "fácil/básico", "medium": "medio", "hard": "difícil"}[difficulty_key]
    header = (
        f"# Preguntas tipo test\n\n"
        f"Documento: {Path(path).name}\n"
        f"Dificultad: {label}\n"
        f"Preguntas: {question_count}\n"
        f"Opciones por pregunta: {options_per_question}\n"
        "Cada pregunta tiene una sola respuesta correcta.\n"
    )
    solucionario = "## Solucionario\n\n" + "\n".join(answer_key) + "\n"
    return header + "\n".join(questions) + solucionario


def _validate_int(value: int, *, name: str, minimum: int, maximum: int) -> tuple[int, str | None]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0, f"Error: {name} must be an integer"
    if parsed < minimum or parsed > maximum:
        return 0, f"Error: {name} must be between {minimum} and {maximum}"
    return parsed, None


def _normalize_difficulty(value: str) -> str | None:
    normalized = str(value or "").strip().lower()
    return _DIFFICULTY_ALIASES.get(normalized)


def _extract_facts(text: str, difficulty: str) -> list[_Fact]:
    sentences = _sentences(text)
    if difficulty == "basic":
        sentences = sorted(sentences, key=len)
    elif difficulty == "hard":
        sentences = sorted(sentences, key=len, reverse=True)

    facts: list[_Fact] = []
    seen_answers: set[str] = set()
    for sentence in sentences:
        answer = _best_answer_phrase(sentence, difficulty)
        if not answer:
            continue
        answer_key = answer.lower()
        if answer_key in seen_answers:
            continue
        stem = _blank_answer(sentence, answer)
        if "_____" not in stem:
            continue
        facts.append(_Fact(sentence=sentence, answer=answer, stem=stem))
        seen_answers.add(answer_key)
    return facts


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\[[^\]]+\]", " ", text)
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    raw_sentences = re.split(r"(?<=[.!?])\s+|(?:\n\s*){2,}", cleaned)
    return [
        sentence.strip(" -•\t")
        for sentence in raw_sentences
        if 40 <= len(sentence.strip()) <= 360 and len(sentence.split()) >= 7
    ]


def _best_answer_phrase(sentence: str, difficulty: str) -> str | None:
    phrases = re.findall(
        r"\b[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÜÑáéíóúüñ-]*){0,3}",
        sentence,
    )
    phrases.extend(re.findall(r"\b\d+(?:[.,]\d+)?(?:\s*%|\s+\w+)?", sentence))
    candidates = [
        phrase.strip()
        for phrase in phrases
        if 2 <= len(phrase.strip()) <= 60 and not _is_stopwordish(phrase)
    ]
    if not candidates:
        words = [
            word.strip(".,;:()[]")
            for word in sentence.split()
            if len(word.strip(".,;:()[]")) >= 6 and not _is_stopwordish(word)
        ]
        candidates = words
    if not candidates:
        return None
    if difficulty == "hard":
        return max(candidates, key=len)
    if difficulty == "medium":
        return sorted(candidates, key=lambda item: (len(item.split()), len(item)), reverse=True)[0]
    return min(candidates, key=len)


def _is_stopwordish(text: str) -> bool:
    words = [word.lower().strip(".,;:()[]¿?¡!") for word in text.split()]
    return not words or all(word in _STOPWORDS for word in words)


def _blank_answer(sentence: str, answer: str) -> str:
    pattern = re.compile(re.escape(answer), flags=re.IGNORECASE)
    return pattern.sub("_____", sentence, count=1)


def _build_options(
    correct_answer: str,
    facts: list[_Fact],
    current_index: int,
    options_per_question: int,
) -> list[tuple[str, bool]]:
    distractors: list[str] = []
    seen = {correct_answer.lower()}
    for offset in range(1, len(facts) + 1):
        candidate = facts[(current_index + offset) % len(facts)].answer
        key = candidate.lower()
        if key in seen:
            continue
        distractors.append(candidate)
        seen.add(key)
        if len(distractors) >= options_per_question - 1:
            break
    while len(distractors) < options_per_question - 1:
        filler = f"Ninguna de las anteriores {len(distractors) + 1}"
        distractors.append(filler)

    correct_position = current_index % options_per_question
    options: list[tuple[str, bool]] = []
    distractor_iter = iter(distractors)
    for pos in range(options_per_question):
        if pos == correct_position:
            options.append((correct_answer, True))
        else:
            options.append((next(distractor_iter), False))
    return options


def _render_question(
    index: int,
    fact: _Fact,
    options: list[tuple[str, bool]],
    difficulty: str,
) -> str:
    if difficulty == "hard":
        prompt = (
            f"{index}. Completa correctamente la afirmación basada en el documento: {fact.stem}"
        )
    elif difficulty == "medium":
        prompt = f"{index}. Según el documento, ¿qué opción completa mejor esta idea? {fact.stem}"
    else:
        prompt = f"{index}. Completa la frase del documento: {fact.stem}"
    lines = [prompt]
    for option_index, (text, is_correct) in enumerate(options):
        marker = " (correcta)" if is_correct else ""
        lines.append(f"   {chr(65 + option_index)}. {text}{marker}")
    return "\n".join(lines) + "\n\n"


def _render_answer_key_entry(index: int, options: list[tuple[str, bool]]) -> str:
    for option_index, (text, is_correct) in enumerate(options):
        if is_correct:
            return f"{index}. {chr(65 + option_index)}. {text}"
    raise ValueError("quiz question has no correct option")
