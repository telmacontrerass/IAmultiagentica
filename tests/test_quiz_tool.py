"""Tests for document-based multiple-choice quiz generation."""

from __future__ import annotations

from pathlib import Path

from ci2lab.harness.tools.quiz import create_quiz_questions
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall


def _write_source(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "La fotosintesis convierte la luz solar en energia quimica para las plantas.",
                "La mitocondria produce ATP mediante la respiracion celular en organismos eucariotas.",
                "El ciclo del agua incluye evaporacion, condensacion y precipitacion en la atmosfera.",
                "La gravedad mantiene a los planetas orbitando alrededor del Sol dentro del sistema solar.",
                "El ADN almacena informacion genetica que se transmite entre generaciones.",
                "La seleccion natural favorece rasgos heredables que mejoran la supervivencia.",
            ]
        ),
        encoding="utf-8",
    )


def test_create_quiz_questions_defaults_to_four_options_and_one_correct(tmp_path: Path) -> None:
    _write_source(tmp_path / "biology.md")

    output = create_quiz_questions(str(tmp_path), "biology.md", 3, "basic")

    assert output.count(". Completa") == 3
    assert output.count(" (correcta)") == 3
    assert output.count("   A.") == 3
    assert output.count("   D.") == 3
    assert "   E." not in output
    assert "## Solucionario" in output
    solucionario = output.split("## Solucionario", 1)[1]
    assert solucionario.count("\n1. ") == 1
    assert solucionario.count("\n2. ") == 1
    assert solucionario.count("\n3. ") == 1
    for block in output.split("\n\n"):
        if ". Completa" in block:
            assert block.count(" (correcta)") == 1


def test_create_quiz_questions_respects_custom_option_count(tmp_path: Path) -> None:
    _write_source(tmp_path / "biology.md")

    output = create_quiz_questions(str(tmp_path), "biology.md", 2, "medio", 3)

    assert output.count(". Según el documento") == 2
    assert output.count(" (correcta)") == 2
    assert output.count("   C.") == 2
    assert "   D." not in output
    assert "## Solucionario" in output


def test_execute_quiz_tool_normalizes_aliases(tmp_path: Path) -> None:
    _write_source(tmp_path / "biology.md")

    result = execute_tool(
        ToolCall(
            name="create_quiz_questions",
            arguments={
                "filepath": "biology.md",
                "n_preguntas": "2",
                "difficulty": "difícil",
                "opciones": "3",
            },
            call_id="quiz1",
        ),
        AgentConfig(cwd=str(tmp_path)),
    )

    assert not result.is_error
    assert "Preguntas: 2" in result.content
    assert "Opciones por pregunta: 3" in result.content
    assert result.content.count(" (correcta)") == 2
