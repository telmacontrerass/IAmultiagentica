from pathlib import Path

from ci2lab.harness.tools.filesystem_parts.mutate import write_file
from ci2lab.harness.tools.placeholder_content import looks_like_placeholder_content


def test_detects_variable_placeholders():
    assert looks_like_placeholder_content("${exercise_1_instructions}")
    assert looks_like_placeholder_content("{{ extracted_instructions }}")
    assert looks_like_placeholder_content("$instructions")
    assert looks_like_placeholder_content("<extracted_instructions>")
    assert looks_like_placeholder_content("<insert extracted instructions for exercise 1 here>")
    assert looks_like_placeholder_content("  ${value}  ")  # surrounding whitespace


def test_does_not_flag_real_content():
    # Real multi-line text, even if it mentions a variable, is fine.
    assert not looks_like_placeholder_content(
        "Exercise 1: implement a function that returns the sum.\nUse recursion."
    )
    # A real template file has surrounding text around the placeholder.
    assert not looks_like_placeholder_content("DATABASE_URL=${DB_URL}")
    assert not looks_like_placeholder_content("")
    assert not looks_like_placeholder_content("Just a normal sentence.")


def test_write_file_rejects_placeholder_and_writes_nothing(tmp_path: Path):
    target = tmp_path / "out.txt"
    result = write_file(str(tmp_path), "out.txt", "${exercise_1_instructions}")

    assert result.startswith("Error:")
    assert "placeholder" in result
    assert not target.exists()  # no useless token file left behind


def test_write_file_accepts_real_content(tmp_path: Path):
    target = tmp_path / "out.txt"
    result = write_file(str(tmp_path), "out.txt", "Exercise 1: write a recursive sum function.")

    assert result.startswith("Wrote")
    assert target.read_text(encoding="utf-8") == "Exercise 1: write a recursive sum function."
