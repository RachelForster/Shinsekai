from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from application.chat.export_playable_vn import PlayableVnExportRequest, export_playable_vn
from application.chat.history.replay_store import ReplayRecorder, ReplayStore
from application.chat.voice_archive import VoiceArchive
from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.storage import remove_chat_history_storage
from sdk.exception.types import AppError


def _setup_history_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project_root = tmp_path
    (project_root / "data" / "backgrounds" / "Room").mkdir(parents=True)
    bg_file = project_root / "data" / "backgrounds" / "Room" / "day.png"
    bg_file.write_bytes(b"\x89PNG\r\n\x1a\nday")
    (project_root / "data" / "sprites" / "Mio").mkdir(parents=True)
    sp_file = project_root / "data" / "sprites" / "Mio" / "smile.png"
    sp_file.write_bytes(b"\x89PNG\r\n\x1a\nsmile")
    (project_root / "cache" / "audio").mkdir(parents=True)
    audio_file = project_root / "cache" / "audio" / "line1.wav"
    audio_file.write_bytes(b"RIFF0000WAVEfmt ")

    history_dir = project_root / "data" / "chat_history" / "sess1"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    turn_id = "turn-1"
    raw_messages = [
        {"role": "user", "content": "[Local time 2026-11-24 10:00:00]\nHi Mio", "input_text": "Hi Mio"},
        {
            "role": "assistant",
            CHAT_TURN_ID: turn_id,
            "content": json.dumps(
                {
                    "dialog": [
                        {"character_name": "Mio", "speech": "Welcome back!", "sprite": 1},
                        {"character_name": "CHOICE", "speech": "Go left / Go right"},
                    ]
                }
            ),
        },
        {"role": "user", "content": "Go left", "input_text": "Go left"},
    ]
    active_file.write_text(json.dumps(raw_messages, ensure_ascii=False), encoding="utf-8")

    ids = DialogIdentities(turn_id)
    dialog_id = ids.next({"character_name": "Mio", "speech": "Welcome back!"})

    recorder = ReplayRecorder(ReplayStore(active_file))
    recorder.observe({"type": "background.change", "url": "/api/media?path=data/backgrounds/Room/day.png"})
    recorder.observe(
        {
            "type": "sprite.show",
            "characterName": "Mio",
            "url": "/api/media?path=data/sprites/Mio/smile.png",
            "scale": 1.0,
            "slot": 0,
            "avatarType": "static",
            "modelUrl": "",
        }
    )
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{dialog_id}'>Mio</p>"})

    monkeypatch.chdir(project_root)
    archive = VoiceArchive(active_file)
    voice_id = "1" * 32
    archive.record(voice_id, str(audio_file), dialog_id=dialog_id)
    archive.complete(voice_id)

    config_manager = SimpleNamespace(
        config=SimpleNamespace(
            system_config=SimpleNamespace(
                ui_language="en",
                chat_ui_theme_id="",
                theme_color="#d4788e",
                user_name="Player",
            ),
            characters=[],
        ),
        get_character_by_name=lambda _name: None,
    )
    history_entries = [
        {"id": "history-0", "role": "user", "text": "You: Hi Mio", "revertUserIndex": 0},
        {"id": "history-1", "role": "assistant", "text": "Mio: Welcome back!", "dialogId": dialog_id},
        {"id": "history-2", "role": "options", "text": "CHOICE: Go left / Go right"},
        {"id": "history-3", "role": "user", "text": "You: Go left", "revertUserIndex": 1},
    ]
    state = SimpleNamespace(
        project_root_dir=str(project_root),
        template_dir_path=str(project_root / "data" / "character_templates"),
        history_dir=str(project_root / "data" / "chat_history"),
        chat_session={"sessionId": "s1", "historyPath": str(active_file), "conversationTitle": "Morning Chat"},
        config_manager=config_manager,
    )
    monkeypatch.setattr("application.chat.export_playable_vn._chat_history", lambda _st: list(history_entries))
    monkeypatch.setattr(
        "application.chat.export_playable_vn.resolve_history_path_for_project",
        lambda _st, raw: Path(raw),
    )
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)
    return state, active_file


def test_export_playable_vn_active_range_and_conversation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, active_file = _setup_history_fixture(tmp_path, monkeypatch)
    try:
        outcome = export_playable_vn(
            state,
            PlayableVnExportRequest(
                start_entry_id="history-1",
                end_entry_id="history-3",
                output_format="zip",
                user_display_name="Hero",
            ),
        )
        assert outcome.is_project_relative is True
        assert "/api/download" not in outcome.path
        assert outcome.entry_count == 2  # history-2 (CHOICE) omitted
        assert outcome.voice_count == 1
        assert (tmp_path / outcome.path).is_file()
        with zipfile.ZipFile(tmp_path / outcome.path) as zf:
            data_name = next(n for n in zf.namelist() if n.startswith("story-data."))
            payload = json.loads(zf.read(data_name).decode("utf-8").split("=", 1)[1].rstrip(";\n"))
            assert len(payload["entries"]) == 2
            assert all(e["role"] != "options" for e in payload["entries"])
            assert payload["entries"][0]["speaker"] == "Mio"
            assert payload["entries"][0]["background"].startswith("./assets/bg/")
            assert payload["entries"][1]["role"] == "user"
            assert payload["entries"][1]["speaker"] == "Hero"
            assert payload["entries"][1]["text"] == "Go left"

        choice_end = export_playable_vn(
            state,
            PlayableVnExportRequest(
                start_entry_id="history-1",
                end_entry_id="history-2",
                output_format="zip",
                user_display_name="Hero",
            ),
        )
        assert choice_end.entry_count == 1

        monkeypatch.setattr(
            "application.chat.export_playable_vn.list_conversation_records",
            lambda _st: {"conv-1": {"historyPath": str(active_file), "title": "Saved Story"}},
        )
        dir_outcome = export_playable_vn(
            state,
            PlayableVnExportRequest(
                conversation_id="conv-1",
                output_format="directory",
                output_dir=str(tmp_path / "custom_dir"),
                user_display_name="你",
            ),
        )
        assert dir_outcome.format == "directory"
        assert (tmp_path / "custom_dir" / "index.html").is_file()
    finally:
        remove_chat_history_storage(active_file)


def test_export_playable_vn_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        chat_session={},
        config_manager=SimpleNamespace(config=SimpleNamespace(system_config=SimpleNamespace(ui_language="en"))),
    )
    with pytest.raises(AppError) as empty_exc:
        export_playable_vn(state, PlayableVnExportRequest())
    assert empty_exc.value.error_code == "vn_export_empty_history"

    with pytest.raises(AppError) as fmt_exc:
        export_playable_vn(state, PlayableVnExportRequest(output_format="tar"))  # type: ignore[arg-type]
    assert fmt_exc.value.error_code == "vn_export_invalid_output"

    monkeypatch.setattr("application.chat.export_playable_vn.list_conversation_records", lambda _st: {})
    with pytest.raises(AppError) as conv_exc:
        export_playable_vn(state, PlayableVnExportRequest(conversation_id="missing"))
    assert conv_exc.value.error_code == "vn_export_conversation_not_found"


def _read_story_payload(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        data_name = next(n for n in zf.namelist() if n.startswith("story-data."))
        return json.loads(zf.read(data_name).decode("utf-8").split("=", 1)[1].rstrip(";\n"))


def test_export_resolves_bridge_media_urls_and_empty_frame_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data" / "backgrounds" / "Room").mkdir(parents=True)
    (tmp_path / "data" / "backgrounds" / "Room" / "day.png").write_bytes(b"\x89PNG\r\n\x1a\nday")
    (tmp_path / "data" / "sprite" / "Mio").mkdir(parents=True)
    (tmp_path / "data" / "sprite" / "Mio" / "s1.png").write_bytes(b"\x89PNG\r\n\x1a\ns1")
    (tmp_path / "data" / "sprite" / "Mio" / "s2.png").write_bytes(b"\x89PNG\r\n\x1a\ns2")
    (tmp_path / "data" / "speech" / "Mio").mkdir(parents=True)
    preset_wav = tmp_path / "data" / "speech" / "Mio" / "p2.wav"
    preset_wav.write_bytes(b"RIFF0000WAVEfmt preset2")
    ref_wav = tmp_path / "data" / "speech" / "Mio" / "ref1.wav"
    ref_wav.write_bytes(b"RIFF0000WAVEfmt ref1")

    history_dir = tmp_path / "data" / "chat_history" / "sess_bridge"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    turn_id = "turn-bridge"
    raw_messages = [
        {
            "role": "assistant",
            CHAT_TURN_ID: turn_id,
            "content": json.dumps(
                {
                    "dialog": [
                        {"character_name": "Mio", "speech": "Line one", "sprite": "01"},
                        {"character_name": "Mio", "speech": "Line two", "sprite": "02"},
                    ]
                }
            ),
        },
        {"role": "user", "content": "Reply after", "input_text": "Reply after"},
    ]
    active_file.write_text(json.dumps(raw_messages, ensure_ascii=False), encoding="utf-8")

    ids = DialogIdentities(turn_id)
    d1 = ids.next({"character_name": "Mio", "speech": "Line one", "sprite": "01"})
    d2 = ids.next({"character_name": "Mio", "speech": "Line two", "sprite": "02"})

    recorder = ReplayRecorder(ReplayStore(active_file))
    recorder.observe(
        {
            "type": "background.change",
            "url": "http://127.0.0.1:8765/api/media?path=data%2Fbackgrounds%2FRoom%2Fday.png&shinsekai_bridge_token=tok",
        }
    )
    recorder.observe(
        {
            "type": "sprite.show",
            "characterName": "Mio",
            "url": "http://127.0.0.1:8765/api/media?path=data%2Fsprite%2FMio%2Fs2.png&shinsekai_bridge_token=tok",
            "scale": 1.0,
            "slot": 0,
            "avatarType": "static",
            "modelUrl": "",
        }
    )
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{d2}'>Mio</p>"})
    # Write a frame.json with empty sprites list for d1 to verify fallback kicks in.
    ReplayStore(active_file).write(
        d1,
        "frame.json",
        {
            "backgroundPath": "http://127.0.0.1:8765/api/media?path=data/backgrounds/Room/day.png&shinsekai_bridge_token=tok",
            "bgmPath": "",
            "cgPath": "",
            "ambientEffects": [],
            "sprites": [],
            "stats": [],
        },
    )

    mio_char = SimpleNamespace(
        name="Mio",
        avatar_type="static",
        sprite_scale=1.0,
        speech_volume=0.8,
        sprites=[
            {"path": "./data/sprite\\Mio\\s1.png", "voice_path": "./data/speech\\Mio\\ref1.wav", "voice_type": "reference"},
            {"path": "./data/sprite\\Mio\\s2.png", "voice_path": "./data/speech\\Mio\\p2.wav", "voice_type": "preset"},
        ],
    )
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        chat_session={"sessionId": "s2", "historyPath": str(active_file)},
        config_manager=SimpleNamespace(
            config=SimpleNamespace(system_config=SimpleNamespace(ui_language="en", chat_ui_theme_id="", theme_color="")),
            get_character_by_name=lambda n: mio_char if n == "Mio" else None,
        ),
    )
    history_entries = [
        {"id": "history-0", "role": "assistant", "text": "Mio: Line one", "dialogId": d1},
        {"id": "history-1", "role": "assistant", "text": "Mio: Line two", "dialogId": d2},
        {"id": "history-2", "role": "user", "text": "You: Reply after", "revertUserIndex": 0},
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("application.chat.export_playable_vn._chat_history", lambda _st: list(history_entries))
    monkeypatch.setattr("application.chat.export_playable_vn.resolve_history_path_for_project", lambda _st, raw: Path(raw))
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)

    try:
        outcome = export_playable_vn(state, PlayableVnExportRequest(output_format="zip"))
        payload = _read_story_payload(tmp_path / outcome.path)
        e0, e1, e2 = payload["entries"]
        assert e0["background"].startswith("./assets/bg/")
        assert len(e0["sprites"]) == 1 and e0["sprites"][0]["url"].startswith("./assets/sprites/")
        assert e0["voices"] == []  # reference audio must NOT be exported as speech
        assert len(e1["sprites"]) == 1 and e1["sprites"][0]["url"].startswith("./assets/sprites/")
        assert len(e1["voices"]) == 1 and e1["voices"][0].startswith("./assets/voice/")
        assert len(e2["sprites"]) == 1  # persisted across user turn
    finally:
        remove_chat_history_storage(active_file)


def test_export_legacy_zero_padded_sprite_fallback_voice_and_chain_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "proj"
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    (project_root / "data" / "sprite" / "Kyoko").mkdir(parents=True)
    (project_root / "data" / "sprite" / "Kyoko" / "sp1.png").write_bytes(b"\x89PNG\r\n\x1a\n1")
    (project_root / "data" / "sprite" / "Kyoko" / "sp2.png").write_bytes(b"\x89PNG\r\n\x1a\n2")
    (project_root / "data" / "speech" / "Kyoko").mkdir(parents=True)
    (project_root / "data" / "speech" / "Kyoko" / "v2.wav").write_bytes(b"RIFF0000WAVEfmt fb2")
    (project_root / "cache" / "audio").mkdir(parents=True)
    cached_wav = project_root / "cache" / "audio" / "cached1.wav"
    cached_wav.write_bytes(b"RIFF0000WAVEfmt cached")
    (project_root / "data" / "chat_history" / "sess_chain").mkdir(parents=True)

    active_file = project_root / "data" / "chat_history" / "sess_chain" / "active.json"
    raw_messages = [
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "dialog": [
                        {"character_name": "场景", "speech": "Hallway"},
                        {"character_name": "Kyoko", "speech": "Hello", "sprite": "01"},
                        {"character_name": "Kyoko", "speech": "Look", "sprite": "02"},
                        {"character_name": "Kyoko", "speech": "Goodbye", "sprite": "02", "effect": "LEAVE"},
                    ]
                }
            ),
        }
    ]
    active_file.write_text(json.dumps(raw_messages, ensure_ascii=False), encoding="utf-8")

    # Compute ReplayStore keys exactly as ChatReplayService.prepare does (hashing hidden rows first).
    from application.chat.history.replay import digest
    from core.chat_history.storage import legacy_active_history_branch

    history_entries = [
        {"id": "history-0", "role": "system", "text": "场景: Hallway"},
        {"id": "history-1", "role": "assistant", "text": "Kyoko: Hello"},
        {"id": "history-2", "role": "assistant", "text": "Kyoko: Look"},
        {"id": "history-3", "role": "assistant", "text": "Kyoko: Goodbye"},
    ]
    chain = digest([str(active_file), legacy_active_history_branch(active_file)])
    chains = []
    for row in history_entries:
        chain = digest([chain, row.get("role"), row.get("text"), row.get("dialogId")])
        chains.append(chain)

    store = ReplayStore(active_file)
    file_key = "a" * 64
    store.directory.mkdir(parents=True, exist_ok=True)
    store.path(file_key, "wav").write_bytes(b"RIFF0000WAVEfmt replay_chain")
    store.write(chains[1], "voice.json", {"fileKey": file_key, "speechKey": "s", "source": "generated"})

    # Also test VoiceArchive with complete=False and cache dir inside project_root while cwd != project_root.
    monkeypatch.chdir(project_root)
    archive = VoiceArchive(active_file)
    d3_id = "d" * 64
    history_entries[3]["dialogId"] = d3_id
    voice_id = "2" * 32
    archive.record(voice_id, str(cached_wav), dialog_id=d3_id)  # complete remains False
    monkeypatch.chdir(other_cwd)

    kyoko_char = SimpleNamespace(
        name="Kyoko",
        avatar_type="static",
        sprite_scale=1.0,
        speech_volume=1.0,
        sprites=[
            {"path": "./data/sprite\\Kyoko\\sp1.png", "voice_path": None, "voice_type": None},
            {"path": "./data/sprite\\Kyoko\\sp2.png", "voice_path": "./data/speech\\Kyoko\\v2.wav", "voice_type": "fallback"},
        ],
    )
    state = SimpleNamespace(
        project_root_dir=str(project_root),
        chat_session={"sessionId": "s3", "historyPath": str(active_file)},
        config_manager=SimpleNamespace(
            config=SimpleNamespace(system_config=SimpleNamespace(ui_language="zh_CN", chat_ui_theme_id="", theme_color="")),
            get_character_by_name=lambda n: kyoko_char if n == "Kyoko" else None,
        ),
    )
    monkeypatch.setattr("application.chat.export_playable_vn._chat_history", lambda _st: list(history_entries))
    monkeypatch.setattr("application.chat.export_playable_vn.resolve_history_path_for_project", lambda _st, raw: Path(raw))
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)

    try:
        outcome = export_playable_vn(state, PlayableVnExportRequest(output_format="zip"))
        assert outcome.entry_count == 3  # 场景 hidden
        assert outcome.voice_count == 3  # line1 via chain voice.json, line2 via sprite fallback wav, line3 via incomplete archive cache
        payload = _read_story_payload(project_root / outcome.path)
        e0, e1, e2 = payload["entries"]
        assert len(e0["sprites"]) == 1 and len(e0["voices"]) == 1
        assert len(e1["sprites"]) == 1 and e1["sprites"][0]["url"] != e0["sprites"][0]["url"]
        assert len(e1["voices"]) == 1
        assert e2["sprites"] == []  # removed on LEAVE
        assert len(e2["voices"]) == 1
    finally:
        remove_chat_history_storage(active_file)

