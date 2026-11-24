"""Focused regression tests for VN export review findings and cross-platform guards."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from application.chat.export_vn.export_playable_vn import PlayableVnExportRequest, export_playable_vn
from application.chat.export_vn.metadata import extract_vn_theme_vars
from application.chat.export_vn.resolvers import _relative_media_candidates
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
