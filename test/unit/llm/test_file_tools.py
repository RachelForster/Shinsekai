from __future__ import annotations

from pathlib import Path

from ai.tools.file_tools import file_write


def test_file_write_accepts_absolute_path_outside_working_directory(
    tmp_path: Path,
    monkeypatch,
):
    working_dir = tmp_path / "project"
    working_dir.mkdir()
    destination = tmp_path / "external" / "notes.txt"
    monkeypatch.chdir(working_dir)

    result = file_write(str(destination), "approved content")

    assert result["written"] == str(destination.resolve())
    assert destination.read_text(encoding="utf-8") == "approved content"
