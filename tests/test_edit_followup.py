from pathlib import Path

from ci2lab.harness.edit_followup import process_edit_round, stale_old_string_hint
from ci2lab.harness.types import ToolCall, ToolResult


def test_edit_followup_mentions_user_file_when_path_missing():
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: no existe el archivo C:\\proj\\src\\main.py",
            is_error=True,
        )
    ]
    followup = process_edit_round(
        [ToolCall(name="edit_file", arguments={"path": "src/main.py"})],
        results,
        cwd=".",
        user_prompt="read Pruebas.py and change line 3",
        completed_edits=set(),
    )
    assert followup is not None
    assert "Pruebas.py" in followup
    assert "src/main.py" in followup


def test_success_followup_after_edit_file(tmp_path: Path):
    target = tmp_path / "Pruebas.py"
    target.write_text("linea tres\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "Pruebas.py",
                "old_string": "linea tres",
                "new_string": "Decimocuarto intento",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content=f"Editado {target}: 1 reemplazo(s)",
            is_error=False,
        )
    ]
    completed: set[tuple[str, str, str]] = set()

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change line 3 of Pruebas.py",
        completed_edits=completed,
    )

    assert followup is not None
    assert "se aplicó correctamente" in followup
    assert ("Pruebas.py", "linea tres", "Decimocuarto intento") in completed


def test_redundant_edit_followup_when_change_already_in_file(tmp_path: Path):
    target = tmp_path / "Pruebas.py"
    target.write_text("Decimocuarto intento\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "Pruebas.py",
                "old_string": "linea tres",
                "new_string": "Decimocuarto intento",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string no encontrado en el archivo",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change Pruebas.py",
        completed_edits=set(),
    )

    assert followup is not None
    assert "ya está aplicado" in followup
    assert "Vuelve a llamar a read_file" not in followup


def test_redundant_edit_followup_when_recorded_in_session(tmp_path: Path):
    target = tmp_path / "Pruebas.py"
    target.write_text("Decimocuarto intento\n", encoding="utf-8")
    sig = ("Pruebas.py", "linea tres", "Decimocuarto intento")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": sig[0],
                "old_string": sig[1],
                "new_string": sig[2],
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string no encontrado en el archivo",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change Pruebas.py",
        completed_edits={sig},
    )

    assert followup is not None
    assert "ya está aplicado" in followup


def test_stale_old_string_hint_shows_current_file_content(tmp_path: Path):
    target = tmp_path / "Pruebas.py"
    target.write_text(
        "# archivo de prueba\nlinea dos\nDecimocuarto intento\nlinea cuatro\n",
        encoding="utf-8",
    )

    hint = stale_old_string_hint(str(tmp_path), "Pruebas.py", "linea tres")

    assert hint is not None
    assert "Decimocuarto intento" in hint
    assert "ya no está" in hint


def test_stale_old_string_followup_on_failed_edit(tmp_path: Path):
    target = tmp_path / "Pruebas.py"
    target.write_text("Decimocuarto intento\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "Pruebas.py",
                "old_string": "linea tres",
                "new_string": "No se cuantos intentos",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string no encontrado en el archivo",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="change Pruebas.py line 3",
        completed_edits=set(),
    )

    assert followup is not None
    assert "Decimocuarto intento" in followup
    assert "ya está aplicado" not in followup


def test_missing_old_string_still_suggests_read_file(tmp_path: Path):
    target = tmp_path / "a.txt"
    target.write_text("contenido distinto\n", encoding="utf-8")
    calls = [
        ToolCall(
            name="edit_file",
            arguments={
                "path": "a.txt",
                "old_string": "no existe",
                "new_string": "nuevo",
            },
        )
    ]
    results = [
        ToolResult(
            tool_name="edit_file",
            content="Error: old_string no encontrado en el archivo",
            is_error=True,
        )
    ]

    followup = process_edit_round(
        calls,
        results,
        cwd=str(tmp_path),
        user_prompt="edit a.txt",
        completed_edits=set(),
    )

    assert followup is not None
    assert "read_file" in followup
    assert "ya está aplicado" not in followup
