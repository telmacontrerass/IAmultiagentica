import os
import tempfile

from ci2lab.harness.tools.filesystem import read_file, write_file, edit_file, ls
from ci2lab.harness.tools.paths import PathViolationError, resolve_path


def test_resolve_path_blocks_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            resolve_path("..", tmp)
            assert False, "debería fallar"
        except PathViolationError:
            pass


def test_read_write_edit_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        write_file(tmp, "a.txt", "hello world")
        assert "hello" in read_file(tmp, "a.txt")
        edit_file(tmp, "a.txt", "world", "ci2lab")
        assert "ci2lab" in read_file(tmp, "a.txt")
        listing = ls(tmp, ".")
        assert "a.txt" in listing
