from pathlib import Path

import pytest

from application.chat.voice_archive import VoiceArchive


VOICE_ID = "a" * 32


def test_cache_voice_expires_after_slot_is_reused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "cache" / "audio"
    cache.mkdir(parents=True)
    clip = cache / "0.wav"
    clip.write_bytes(b"first voice")
    archive = VoiceArchive(tmp_path / "data" / "chat_history" / "session")

    archive.record(VOICE_ID, str(clip))
    archive.complete(VOICE_ID)
    assert archive.source(VOICE_ID, 0) == clip

    clip.write_bytes(b"new voice in the same slot")
    with pytest.raises(ValueError, match="语音失效"):
        archive.source(VOICE_ID, 0)
    with pytest.raises(ValueError, match="语音失效"):
        archive.save_voice(VOICE_ID)


def test_toggle_archives_available_voices_and_manual_save_uses_save_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "cache" / "audio"
    cache.mkdir(parents=True)
    clip = cache / "0.wav"
    clip.write_bytes(b"first voice")
    session = tmp_path / "data" / "chat_history" / "session"
    archive = VoiceArchive(session)
    archive.record(VOICE_ID, str(clip))
    archive.complete(VOICE_ID)

    archive.set_enabled(True)
    assert (session / "audio" / f"{VOICE_ID}-0.wav").read_bytes() == b"first voice"
    archive.save_voice(VOICE_ID)
    assert (session / "audio" / "save" / f"{VOICE_ID}-0.wav").read_bytes() == b"first voice"

    clip.write_bytes(b"new voice in the same slot")
    reopened = VoiceArchive(session)
    assert reopened.enabled
    assert reopened.source(VOICE_ID, 0).read_bytes() == b"first voice"


def test_manual_save_while_off_uses_audio_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / "cache" / "audio"
    cache.mkdir(parents=True)
    clip = cache / "0.wav"
    clip.write_bytes(b"voice")
    session = tmp_path / "data" / "chat_history" / "session"
    archive = VoiceArchive(session)
    archive.record(VOICE_ID, str(clip))
    archive.complete(VOICE_ID)

    archive.save_voice(VOICE_ID)
    assert (session / "audio" / f"{VOICE_ID}-0.wav").read_bytes() == b"voice"
    assert not (session / "audio" / "save").exists()
