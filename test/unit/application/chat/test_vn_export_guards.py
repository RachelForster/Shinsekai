"""Focused regression tests for VN export review findings and cross-platform guards."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from application.chat.export_vn.export_playable_vn import PlayableVnExportRequest, export_playable_vn
from application.chat.export_vn.metadata import extract_vn_theme_vars
from application.chat.export_vn.resolvers import _relative_media_candidates
from application.chat.history.replay_store import ReplayRecorder, ReplayStore
from application.chat.voice_archive import VoiceArchive
from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.storage import remove_chat_history_storage
from core.storage.chat_theme_store import read_chat_theme_manifest
from sdk.exception.types import AppError


def _read_story_payload(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        data_name = next(n for n in zf.namelist() if n.startswith("story-data."))
        return json.loads(zf.read(data_name).decode("utf-8").split("=", 1)[1].rstrip(";\n"))


def _make_state(
    project_root: Path,
    active_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    history_entries: list[dict],
    *,
    session_id: str = "sess-1",
    theme_id: str = "",
) -> SimpleNamespace:
    monkeypatch.setattr("application.chat.export_vn.export_playable_vn._chat_history", lambda _st: list(history_entries))
    monkeypatch.setattr("application.chat.export_vn.export_playable_vn.resolve_history_path_for_project", lambda _st, raw: Path(raw))
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)
    return SimpleNamespace(
        project_root_dir=str(project_root),
        chat_session={"sessionId": session_id, "historyPath": str(active_file)},
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                system_config=SimpleNamespace(ui_language="en", chat_ui_theme_id=theme_id, theme_color="#d4788e")
            ),
            get_character_by_name=lambda _name: None,
        ),
    )


def test_posix_relative_media_candidates_include_slash_normalized_path() -> None:
    candidates = _relative_media_candidates("./data/sprite\\Mio\\s1.png")
    assert "./data/sprite/Mio/s1.png" in candidates
    speech_candidates = _relative_media_candidates("./data/speech\\Mio\\p1.wav")
    assert "./data/speech/Mio/p1.wav" in speech_candidates


def test_story_id_distinguishes_branch_and_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history_dir = tmp_path / "data" / "chat_history" / "sess_branch"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    active_file.write_text("[]", encoding="utf-8")
    branches_file = history_dir / "branches.json"
    entries_a = [
        {"id": "history-0", "role": "assistant", "text": "Mio: Line A"},
        {"id": "history-1", "role": "user", "text": "You: Reply A"},
    ]
    branches_file.write_text(json.dumps({"version": 1, "activeBranchId": "main", "branches": {"main": {"id": "main"}}}), encoding="utf-8")
    state = _make_state(tmp_path, active_file, monkeypatch, entries_a)

    try:
        out_a = export_playable_vn(state, PlayableVnExportRequest(output_format="zip", include_voices=False))
        id_a = _read_story_payload(tmp_path / out_a.path)["storyId"]

        # Same positional IDs and content, different branch -> distinct storyId
        branches_file.write_text(json.dumps({"version": 1, "activeBranchId": "branch-2", "branches": {"branch-2": {"id": "branch-2"}}}), encoding="utf-8")
        out_b = export_playable_vn(state, PlayableVnExportRequest(output_format="zip", include_voices=False))
        id_b = _read_story_payload(tmp_path / out_b.path)["storyId"]
        assert id_b != id_a

        # Same branch and IDs, modified text -> distinct storyId
        entries_c = [
            {"id": "history-0", "role": "assistant", "text": "Mio: Different line"},
            {"id": "history-1", "role": "user", "text": "You: Reply A"},
        ]
        state_c = _make_state(tmp_path, active_file, monkeypatch, entries_c)
        out_c = export_playable_vn(state_c, PlayableVnExportRequest(output_format="zip", include_voices=False))
        id_c = _read_story_payload(tmp_path / out_c.path)["storyId"]
        assert id_c != id_b
    finally:
        remove_chat_history_storage(active_file)


def test_exact_selection_anchors_and_session_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history_dir = tmp_path / "data" / "chat_history" / "sess_exact"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    active_file.write_text("[]", encoding="utf-8")
    entries = [
        {"id": "history-0", "role": "user", "text": "You: First"},
        {"id": "history-1", "role": "assistant", "text": "Mio: Skipped middle"},
        {"id": "history-2", "role": "options", "text": "CHOICE: A / B"},
        {"id": "history-3", "role": "user", "text": "You: Chosen A"},
    ]
    state = _make_state(tmp_path, active_file, monkeypatch, entries, session_id="sess-live")

    try:
        # Non-contiguous selection omits middle row cleanly.
        outcome = export_playable_vn(
            state,
            PlayableVnExportRequest(
                selected_entry_ids=("history-0", "history-3"),
                expected_session_id="sess-live",
                selected_entry_anchors=(
                    {"id": "history-0", "role": "user", "dialogId": "", "text": "You: First"},
                    {"id": "history-3", "role": "user", "dialogId": "", "text": "You: Chosen A"},
                ),
                output_format="zip",
                include_voices=False,
            ),
        )
        payload = _read_story_payload(tmp_path / outcome.path)
        assert [row["id"] for row in payload["entries"]] == ["history-0", "history-3"]

        # Stale session ID is rejected cleanly.
        with pytest.raises(AppError) as sess_exc:
            export_playable_vn(state, PlayableVnExportRequest(expected_session_id="sess-other", include_voices=False))
        assert sess_exc.value.error_code == "vn_export_session_changed"
        assert sess_exc.value.http_status == 409

        # Changed text on same positional ID is rejected via anchor check.
        with pytest.raises(AppError) as anchor_exc:
            export_playable_vn(
                state,
                PlayableVnExportRequest(
                    selected_entry_ids=("history-0",),
                    expected_session_id="sess-live",
                    selected_entry_anchors=({"id": "history-0", "role": "user", "dialogId": "", "text": "You: Stale"},),
                    include_voices=False,
                ),
            )
        assert anchor_exc.value.error_code == "vn_export_history_changed"
        assert anchor_exc.value.http_status == 409
    finally:
        remove_chat_history_storage(active_file)


def test_voice_disabled_ignores_corrupt_archive_and_option_only_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_dir = tmp_path / "data" / "chat_history" / "sess_corrupt_voice"
    (history_dir / "audio").mkdir(parents=True)
    active_file = history_dir / "active.json"
    active_file.write_text("[]", encoding="utf-8")
    (history_dir / "audio" / "index.json").write_text("{corrupt-json", encoding="utf-8")

    entries = [
        {"id": "history-0", "role": "assistant", "text": "Mio: Text line"},
        {"id": "history-1", "role": "options", "text": "CHOICE: X / Y"},
    ]
    state = _make_state(tmp_path, active_file, monkeypatch, entries)

    try:
        outcome = export_playable_vn(
            state,
            PlayableVnExportRequest(output_format="zip", include_voices=False),
        )
        assert outcome.entry_count == 1
        assert outcome.voice_count == 0

        with pytest.raises(AppError) as opt_exc:
            export_playable_vn(
                state,
                PlayableVnExportRequest(start_entry_id="history-1", end_entry_id="history-1", include_voices=False),
            )
        assert opt_exc.value.error_code == "vn_export_no_playable_entries"

        with pytest.raises(AppError) as sel_opt_exc:
            export_playable_vn(
                state,
                PlayableVnExportRequest(selected_entry_ids=("history-1",), include_voices=False),
            )
        assert sel_opt_exc.value.error_code == "vn_export_no_playable_entries"
    finally:
        remove_chat_history_storage(active_file)


def test_output_io_errors_map_to_structured_app_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_dir = tmp_path / "data" / "chat_history" / "sess_io_err"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    active_file.write_text("[]", encoding="utf-8")
    entries = [{"id": "history-0", "role": "assistant", "text": "Mio: Line"}]
    state = _make_state(tmp_path, active_file, monkeypatch, entries)

    try:
        def raise_perm(*_args, **_kwargs):
            raise PermissionError("read-only dir")

        monkeypatch.setattr("application.chat.export_vn.export_playable_vn.export_playable_vn_package", raise_perm)
        with pytest.raises(AppError) as perm_exc:
            export_playable_vn(state, PlayableVnExportRequest(include_voices=False))
        assert perm_exc.value.error_code == "vn_export_invalid_output"
        assert perm_exc.value.http_status == 400

        def raise_os(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("application.chat.export_vn.export_playable_vn.export_playable_vn_package", raise_os)
        with pytest.raises(AppError) as io_exc:
            export_playable_vn(state, PlayableVnExportRequest(include_voices=False))
        assert io_exc.value.error_code == "vn_export_output_io_failed"
        assert io_exc.value.http_status == 500
    finally:
        remove_chat_history_storage(active_file)


def test_chat_theme_manifest_loaded_via_storage_helper(tmp_path: Path) -> None:
    theme_dir = tmp_path / "data" / "chat_ui_themes" / "velvet"
    theme_dir.mkdir(parents=True)
    (theme_dir / "theme.json").write_text(
        json.dumps({"tokens": {"global": {"themeColor": "#123456"}, "dialog": {"background": "rgba(1,2,3,0.8)"}}}),
        encoding="utf-8",
    )
    loaded = read_chat_theme_manifest(tmp_path, "velvet")
    assert loaded["tokens"]["global"]["themeColor"] == "#123456"
    assert read_chat_theme_manifest(tmp_path, "../escape") == {}

    css_vars = extract_vn_theme_vars(tmp_path, "velvet")
    assert css_vars["--vn-accent"] == "#123456"
    assert css_vars["--vn-dialog-bg"] == "rgba(1,2,3,0.8)"


def test_export_recovers_user_turn_dialog_ids_multichar_sprites_and_synth_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "proj"
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    for folder, name, payload in (
        ("sprite/Alice", "a1.png", b"\x89PNG\r\n\x1a\nalice1"),
        ("sprite/Alice", "a2.png", b"\x89PNG\r\n\x1a\nalice2"),
        ("sprite/Bob", "b1.png", b"\x89PNG\r\n\x1a\nbob1"),
        ("speech/Alice", "fallback.wav", b"RIFF0000WAVEfmt fallback"),
        ("cache/audio", "0.wav", b"RIFF0000WAVEfmt synth1"),
        ("cache/audio", "1.wav", b"RIFF0000WAVEfmt synth2"),
    ):
        target = project_root / "data" / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    history_dir = project_root / "data" / "chat_history" / "sess_uturn"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    turn_id = "turn-user-1"
    dialog_items = [
        {"character_name": "Alice", "vibe": "calm", "speech": "Line 1"},
        {"character_name": "Bob", "vibe": "grin", "speech": "Line 2"},
        {"character_name": "Alice", "vibe": "smile", "speech": "Line 3"},
    ]
    raw_messages = [
        {"role": "user", CHAT_TURN_ID: turn_id, "content": "Start", "input_text": "Start"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "{}"},
        {"role": "assistant", "content": json.dumps({"dialog": dialog_items}, ensure_ascii=False)},
    ]
    active_file.write_text(json.dumps(raw_messages, ensure_ascii=False), encoding="utf-8")

    ids = DialogIdentities(turn_id)
    d1, d2, d3 = (ids.next(item) for item in dialog_items)
    store = ReplayStore(active_file)
    recorder = ReplayRecorder(store)
    recorder.observe({"type": "sprite.show", "characterName": "Alice", "url": "/api/media?path=data/sprite/Alice/a1.png", "scale": 1.0, "slot": 0, "avatarType": "static", "modelUrl": ""})
    recorder.observe({"type": "sprite.show", "characterName": "Bob", "url": "/api/media?path=data/sprite/Bob/b1.png", "scale": 1.0, "slot": 1, "avatarType": "static", "modelUrl": ""})
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{d1}'>Alice</p>"})
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{d2}'>Bob</p>"})
    recorder.observe({"type": "sprite.show", "characterName": "Alice", "url": "/api/media?path=data/sprite/Alice/a2.png", "scale": 1.0, "slot": 0, "avatarType": "static", "modelUrl": ""})
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{d3}'>Alice</p>"})

    monkeypatch.chdir(project_root / "data")
    archive = VoiceArchive(active_file)
    archive.record("a" * 32, str(project_root / "data" / "cache" / "audio" / "0.wav"), dialog_id=d1)
    archive.complete("a" * 32)
    archive.record("b" * 32, str(project_root / "data" / "cache" / "audio" / "1.wav"), dialog_id=d2)
    archive.complete("b" * 32)
    monkeypatch.chdir(other_cwd)

    alice_char = SimpleNamespace(
        name="Alice", avatar_type="static", sprite_scale=1.0, speech_volume=1.0,
        sprites=[
            {"path": "./data/sprite/Alice/a1.png", "voice_path": "./data/speech/Alice/fallback.wav", "voice_type": "fallback"},
            {"path": "./data/sprite/Alice/a2.png", "voice_path": None, "voice_type": None},
        ],
    )
    bob_char = SimpleNamespace(name="Bob", avatar_type="static", sprite_scale=1.0, speech_volume=1.0, sprites=[{"path": "./data/sprite/Bob/b1.png", "voice_path": None, "voice_type": None}])
    state = SimpleNamespace(
        project_root_dir=str(project_root),
        chat_session={},
        config_manager=SimpleNamespace(
            config=SimpleNamespace(system_config=SimpleNamespace(ui_language="en", chat_ui_theme_id="", theme_color="#d4788e", user_name="Hero")),
            get_character_by_name=lambda n: {"Alice": alice_char, "Bob": bob_char}.get(n),
        ),
    )
    monkeypatch.setattr("application.chat.export_vn.export_playable_vn.list_conversation_records", lambda _st: {"conv-u1": {"historyPath": str(active_file), "title": "Multi"}})
    monkeypatch.setattr("application.chat.export_vn.export_playable_vn.resolve_history_path_for_project", lambda _st, raw: Path(raw))
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)

    try:
        outcome = export_playable_vn(state, PlayableVnExportRequest(conversation_id="conv-u1", output_format="zip"))
        with zipfile.ZipFile(project_root / outcome.path) as zf:
            data_name = next(n for n in zf.namelist() if n.startswith("story-data."))
            payload = json.loads(zf.read(data_name).decode("utf-8").split("=", 1)[1].rstrip(";\n"))
            _u0, e1, e2, e3 = payload["entries"]
            assert [sp["characterName"] for sp in e1["sprites"]] == ["Alice", "Bob"]
            assert [sp["characterName"] for sp in e2["sprites"]] == ["Alice", "Bob"]
            assert e3["sprites"][0]["url"] != e1["sprites"][0]["url"]
            assert len(e1["voices"]) == 1 and len(e2["voices"]) == 1
            v1_bytes = zf.read(e1["voices"][0].lstrip("./"))
            v2_bytes = zf.read(e2["voices"][0].lstrip("./"))
            assert v1_bytes == b"RIFF0000WAVEfmt synth1"
            assert v2_bytes == b"RIFF0000WAVEfmt synth2"
    finally:
        remove_chat_history_storage(active_file)


def test_export_recovers_legacy_frames_without_chat_turn_id_and_prefers_newer_reroll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "legacy"
    for folder, name, payload in (
        ("data/sprite/Mio", "old.png", b"\x89PNG\r\n\x1a\nold-sp"),
        ("data/sprite/Mio", "new.png", b"\x89PNG\r\n\x1a\nnew-sp"),
        ("data/speech/Mio", "fb.wav", b"RIFF0000WAVEfmt fb"),
        ("cache/audio", "old.wav", b"RIFF0000WAVEfmt oldsynth"),
        ("cache/audio", "new.wav", b"RIFF0000WAVEfmt newsynth"),
    ):
        target = project_root / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    history_dir = project_root / "data" / "chat_history" / "sess_legacy"
    history_dir.mkdir(parents=True)
    active_file = history_dir / "active.json"
    raw_messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": json.dumps({"dialog": [{"character_name": "Mio", "speech": "……"}, {"character_name": "Mio", "speech": "Line 2"}]}, ensure_ascii=False)},
    ]
    active_file.write_text(json.dumps(raw_messages, ensure_ascii=False), encoding="utf-8")

    store = ReplayStore(active_file)
    d_old, d_new, d_two = "1" * 64, "2" * 64, "3" * 64
    for did, sp_name, text, ts in (
        (d_old, "old.png", "……", 1_700_000_000),
        (d_new, "new.png", "……", 1_700_000_010),
        (d_two, "new.png", "Line 2", 1_700_000_020),
    ):
        store.write(
            did,
            "frame.json",
            {
                "backgroundPath": "", "bgmPath": "", "cgPath": "", "ambientEffects": [], "stats": [],
                "sprites": [{"characterName": "Mio", "path": f"data/sprite/Mio/{sp_name}", "avatarType": "static", "slot": 0}],
                "message": {"name": "Mio", "text": text},
            },
        )
        os.utime(store.path(did, "frame.json"), (ts, ts))

    monkeypatch.chdir(project_root)
    archive = VoiceArchive(active_file)
    archive.record("c" * 32, str(project_root / "cache" / "audio" / "old.wav"), dialog_id=d_old)
    archive.complete("c" * 32)
    archive.record("d" * 32, str(project_root / "cache" / "audio" / "new.wav"), dialog_id=d_new)
    archive.complete("d" * 32)

    mio_char = SimpleNamespace(
        name="Mio", avatar_type="static", sprite_scale=1.0, speech_volume=1.0,
        sprites=[
            {"path": "./data/sprite/Mio/old.png", "voice_path": "./data/speech/Mio/fb.wav", "voice_type": "fallback"},
            {"path": "./data/sprite/Mio/new.png", "voice_path": None, "voice_type": None},
        ],
    )
    entries = [
        {"id": "h-0", "role": "user", "text": "You: Hi"},
        {"id": "h-1", "role": "assistant", "text": "Mio: ……"},
        {"id": "h-2", "role": "assistant", "text": "Mio: Line 2"},
    ]
    state = _make_state(project_root, active_file, monkeypatch, entries)
    state.config_manager.get_character_by_name = lambda n: mio_char if n == "Mio" else None

    try:
        outcome = export_playable_vn(state, PlayableVnExportRequest(output_format="zip"))
        with zipfile.ZipFile(project_root / outcome.path) as zf:
            data_name = next(n for n in zf.namelist() if n.startswith("story-data."))
            payload = json.loads(zf.read(data_name).decode("utf-8").split("=", 1)[1].rstrip(";\n"))
            _u0, e1, e2 = payload["entries"]
            assert zf.read(e1["sprites"][0]["url"].lstrip("./")) == b"\x89PNG\r\n\x1a\nnew-sp"
            assert zf.read(e2["sprites"][0]["url"].lstrip("./")) == b"\x89PNG\r\n\x1a\nnew-sp"
            assert len(e1["voices"]) == 1
            assert zf.read(e1["voices"][0].lstrip("./")) == b"RIFF0000WAVEfmt newsynth"
    finally:
        remove_chat_history_storage(active_file)
