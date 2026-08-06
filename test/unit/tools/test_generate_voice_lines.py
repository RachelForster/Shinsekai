from __future__ import annotations

from pathlib import Path

import pytest

from tools import generate_voice_lines as module


class RecordingTTS:
    def __init__(self) -> None:
        self.generated: list[dict[str, object]] = []

    def switch_model(self, _gpt_model_path: str, _sovits_model_path: str) -> None:
        pass

    def generate_tts(self, _word: str, **kwargs: object) -> None:
        self.generated.append(kwargs)


def _character(sprite_prefix: str, sprite_count: int = 2) -> dict[str, object]:
    return {
        "name": "Alice",
        "sprite_prefix": sprite_prefix,
        "gpt_model_path": "gpt.ckpt",
        "sovits_model_path": "sovits.pth",
        "refer_audio_path": "reference.wav",
        "prompt_text": "reference",
        "prompt_lang": "en",
        "sprites": [{} for _ in range(sprite_count)],
    }


def test_generate_voice_lines_generates_each_word_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tts = RecordingTTS()
    character = _character("alice")
    saved: list[bool] = []
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "characters", [character])
    monkeypatch.setattr(module, "tts_manager", tts)
    monkeypatch.setattr(
        module,
        "save_characters_to_file",
        lambda: saved.append(True),
    )

    module.generate_voice_lines("Alice", ["first", "second"])

    assert len(tts.generated) == 2
    assert [
        Path(str(call["file_path"])).relative_to(tmp_path).as_posix()
        for call in tts.generated
    ] == [
        "data/speech/alice/alice_voice_00.wav",
        "data/speech/alice/alice_voice_01.wav",
    ]
    assert [
        sprite["voice_path"] for sprite in character["sprites"]  # type: ignore[index]
    ] == [
        "data/speech/alice/alice_voice_00.wav",
        "data/speech/alice/alice_voice_01.wav",
    ]
    assert saved == [True]


def test_generate_voice_lines_rejects_unsafe_sprite_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(module, "characters", [_character("../outside")])
    monkeypatch.setattr(module, "tts_manager", RecordingTTS())

    with pytest.raises(ValueError, match="sprite_prefix"):
        module.generate_voice_lines("Alice", ["first"])

    assert not (tmp_path / "data").exists()
