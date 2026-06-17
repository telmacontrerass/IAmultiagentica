from pathlib import Path

from ci2lab.harness.tools.patch import apply_patch, plan_patch
from ci2lab.harness.tools.registry import execute_tool
from ci2lab.harness.types import AgentConfig, ToolCall


SAMPLE_PATCH = """\
--- a/nota.txt
+++ b/nota.txt
@@ -1,2 +1,2 @@
 hola
-mundo
+ci2lab
"""


def test_apply_patch_replaces_line(tmp_path: Path):
    target = tmp_path / "nota.txt"
    target.write_text("hola\nmundo\n", encoding="utf-8")

    result = apply_patch(str(tmp_path), SAMPLE_PATCH)

    assert result.startswith("Parche aplicado")
    assert target.read_text(encoding="utf-8") == "hola\nci2lab\n"


def test_apply_patch_context_mismatch(tmp_path: Path):
    target = tmp_path / "nota.txt"
    target.write_text("hola\notro\n", encoding="utf-8")

    result = apply_patch(str(tmp_path), SAMPLE_PATCH)

    assert result.startswith("Error:")
    assert "patch context not found" in result or "mundo" in result


def test_plan_patch_creates_new_file(tmp_path: Path):
    patch = """\
--- /dev/null
+++ b/nuevo.txt
@@ -0,0 +1,2 @@
+uno
+dos
"""
    plan, error = plan_patch(str(tmp_path), patch)

    assert error is None
    assert plan is not None
    assert plan.files["nuevo.txt"] in {"uno\ndos", "uno\ndos\n"}


def test_execute_apply_patch_with_auto_confirm(tmp_path: Path):
    target = tmp_path / "nota.txt"
    target.write_text("hola\nmundo\n", encoding="utf-8")
    config = AgentConfig(cwd=str(tmp_path), auto_confirm=True, require_diff_preview=False)

    result = execute_tool(
        ToolCall(name="apply_patch", arguments={"patch": SAMPLE_PATCH}),
        config,
    )

    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "hola\nci2lab\n"


def test_apply_patch_finds_hunk_when_header_line_is_wrong(tmp_path: Path):
    target = tmp_path / "Pruebas.py"
    target.write_text(
        "# archivo de prueba\nlinea dos\nlinea tres\nlinea cuatro\n",
        encoding="utf-8",
    )
    patch = """\
--- a/Pruebas.py
+++ b/Pruebas.py
@@ -2,1 +2,1 @@
-linea tres
+Linea cambiada otra vez
"""
    result = apply_patch(str(tmp_path), patch)

    assert not result.startswith("Error:")
    assert target.read_text(encoding="utf-8") == (
        "# archivo de prueba\nlinea dos\nLinea cambiada otra vez\nlinea cuatro\n"
    )


def test_parse_fenced_apply_patch():
    from ci2lab.harness.parsing import parse_fenced_blocks

    text = """\
```apply_patch
--- a/x.txt
+++ b/x.txt
@@ -1 +1 @@
-a
+b
```
"""
    calls = parse_fenced_blocks(text)
    assert len(calls) == 1
    assert calls[0].name == "apply_patch"
    assert "--- a/x.txt" in calls[0].arguments["patch"]
