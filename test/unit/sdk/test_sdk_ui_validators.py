from __future__ import annotations

import wave
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from sdk.ui import validators


def test_basic_value_and_numeric_validators() -> None:
    assert validators.not_empty(" value ", "name") == (True, "")
    assert validators.not_empty("", "name")[0] is False
    assert validators.not_empty(None)[0] is False
    assert validators.not_none(0) == (True, "")
    assert validators.not_none(None, "value")[0] is False
    assert validators.in_range(3, 1, 5) == (True, "")
    assert validators.in_range(9, 1, 5, "speed")[0] is False
    assert validators.positive(1) == (True, "")
    assert validators.positive(0, "count")[0] is False
    assert validators.non_negative(0) == (True, "")
    assert validators.non_negative(-1, "count")[0] is False


def test_path_validators_handle_empty_missing_and_existing_paths(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    dir_path = tmp_path / "folder"
    file_path.write_text("content", encoding="utf-8")
    dir_path.mkdir()

    assert validators.file_exists(None) == (True, "")
    assert validators.file_exists(file_path) == (True, "")
    assert validators.file_exists(dir_path)[0] is False
    assert validators.dir_exists("") == (True, "")
    assert validators.dir_exists(dir_path) == (True, "")
    assert validators.dir_exists(file_path)[0] is False
    assert validators.path_exists(file_path) == (True, "")
    assert validators.path_exists(tmp_path / "missing")[0] is False
    assert validators.path_is_absolute(file_path) == (True, "")
    assert validators.path_is_absolute("relative/path")[0] is False


def test_string_format_validators() -> None:
    assert validators.ascii_only("abc-123_./") == (True, "")
    assert validators.ascii_only("hello world") == (True, "")
    assert validators.ascii_only("中文", "slug")[0] is False
    assert validators.no_quotes("/tmp/file") == (True, "")
    assert validators.no_quotes('"/tmp/file"', "path")[0] is False
    assert validators.no_quotes('"/tmp/file', "path")[0] is False
    assert validators.valid_url("https://example.test") == (True, "")
    assert validators.valid_url("http://127.0.0.1:8000") == (True, "")
    assert validators.valid_url("ftp://example.test", "url")[0] is False


def test_audio_duration_between_reads_wav_and_rejects_invalid_audio(tmp_path: Path) -> None:
    wav_path = tmp_path / "tone.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 8000)

    assert validators.audio_duration_between(None, 0.1, 2.0) == (True, "")
    assert validators.audio_duration_between(str(wav_path), 0.5, 1.5) == (True, "")
    assert validators.audio_duration_between(str(wav_path), 2.0, 3.0, "audio")[0] is False
    assert validators.audio_duration_between(str(tmp_path / "broken.wav"), 0.1, 2.0)[0] is False


def test_check_all_first_error_and_dialog_helpers(monkeypatch) -> None:
    ok, errors = validators.check_all(
        validators.not_empty("value", "name"),
        validators.not_none(None, "payload"),
        validators.valid_url("bad-url", "callback"),
    )
    assert ok is False
    assert len(errors) == 2

    assert validators.first_error(validators.not_empty("value"), validators.positive(1)) == (
        True,
        "",
    )
    ok, message = validators.first_error(
        validators.not_empty("value"),
        validators.positive(0, "count"),
        validators.valid_url("bad-url", "callback"),
    )
    assert ok is False
    assert "count" in message

    warnings: list[tuple[object, str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, text: warnings.append((parent, title, text)),
    )

    assert validators.warn_if_invalid((True, [])) is True
    assert validators.warn_if_invalid(False, "broken", title="Title") is False
    assert warnings[-1] == (None, "Title", "broken")
    assert validators.validate_or_block(validators.not_empty("", "name"), title="Block") is False
    assert warnings[-1][1] == "Block"
    assert "name" in warnings[-1][2]
