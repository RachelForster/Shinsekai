from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.sprite.chat_branch_storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
    remove_chat_history_storage,
)
from frontend_bridge import _prepare_project_root
from frontend_bridge_core.chat import (
    _chat_history_download_file,
    _chat_history_path,
    _handle_chat_command,
    _issue_chat_history_download_capability,
)
from frontend_bridge_core.handler import FrontendBridgeHandler
from frontend_bridge_core.history_paths import (
    _windows_history_path_kind,
    resolve_history_path_for_project,
)
from frontend_bridge_core.path_utils import (
    resolve_regular_path,
    strip_windows_verbatim_prefix,
)
from frontend_bridge_core.security import safe_project_path


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows path semantics")


def _other_drive(root: Path) -> str:
    return "C:\\" if root.drive.casefold() != "c:" else "D:\\"


def _state(project_root: Path, **values) -> SimpleNamespace:
    defaults = {
        "history_dir": str(project_root / "data" / "chat_history"),
        "project_root_dir": str(project_root),
        "template_dir_path": str(project_root / "data" / "character_templates"),
        "template_generator": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_project_path_compares_plain_and_verbatim_without_rewriting_io_path(
    tmp_path: Path,
) -> None:
    verbatim_root = Path("\\\\?\\" + str(tmp_path))
    plain_target = tmp_path / "data" / "asset.json"
    verbatim_target = Path("\\\\?\\" + str(plain_target))

    assert safe_project_path(plain_target, root=verbatim_root) == plain_target.resolve(strict=False)
    resolved_verbatim = safe_project_path(verbatim_target, root=tmp_path)
    assert str(resolved_verbatim).startswith("\\\\?\\")
    assert strip_windows_verbatim_prefix(str(resolved_verbatim)) == str(
        plain_target.resolve(strict=False)
    )


def test_relative_project_path_keeps_verbatim_root_for_io(tmp_path: Path) -> None:
    resolved = safe_project_path(
        "data/chat_history/session",
        root=Path("\\\\?\\" + str(tmp_path)),
    )

    assert str(resolved).startswith("\\\\?\\")


def test_project_path_reports_cross_drive_as_permission_error(tmp_path: Path) -> None:
    outside = Path(_other_drive(tmp_path)) / "old" / "session.json"

    with pytest.raises(PermissionError, match="different drive"):
        safe_project_path(outside, root=tmp_path)


def test_external_cross_drive_history_is_allowed_and_stays_absolute(tmp_path: Path) -> None:
    history = Path(_other_drive(tmp_path)) / "old-shinsekai" / "session.json"

    resolved = resolve_history_path_for_project(_state(tmp_path), history)

    assert resolved == history
    assert resolved.is_absolute()


def test_relative_history_is_project_managed_and_cannot_escape(tmp_path: Path) -> None:
    state = _state(tmp_path)

    assert resolve_history_path_for_project(
        state, "data/chat_history/session.json"
    ) == (tmp_path / "data" / "chat_history" / "session.json").resolve(strict=False)
    with pytest.raises(PermissionError):
        resolve_history_path_for_project(state, "../outside/session.json")


@pytest.mark.parametrize(
    "raw",
    [
        r"C:relative\session.json",
        r"\rooted\session.json",
        r"\\.\pipe\session.json",
        r"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\session.json",
        r"\\?\PIPE\session",
    ],
)
def test_ambiguous_and_device_history_paths_are_rejected(tmp_path: Path, raw: str) -> None:
    with pytest.raises(ValueError):
        resolve_history_path_for_project(_state(tmp_path), raw)


@pytest.mark.parametrize(
    "raw",
    [
        r"\\server\share\session.json",
        r"\\?\UNC\server\share\session.json",
        r"//server/share/session.json",
        r"//?/UNC/server/share/session.json",
        r"\\?\C:\history\session.json",
    ],
)
def test_supported_unc_and_verbatim_namespaces_are_absolute(raw: str) -> None:
    assert _windows_history_path_kind(raw) == "absolute"


def test_existing_unrelated_directory_is_not_history(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    unrelated = tmp_path / "documents"
    unrelated.mkdir()
    (unrelated / "important.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="not a chat history"):
        resolve_history_path_for_project(_state(project), unrelated)


def test_existing_history_directory_can_be_external(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external-session"
    external.mkdir()
    (external / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")

    assert resolve_history_path_for_project(_state(project), external) == external


def test_nonexistent_external_json_becomes_session_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    history = tmp_path / "external" / "new-session.json"

    resolved = _chat_history_path(
        _state(project),
        {"historyPath": str(history)},
        {"scenario": "scene", "system": "system"},
    )

    assert resolved == history.with_suffix("")


def test_cleanup_never_recursively_deletes_unrelated_files(tmp_path: Path) -> None:
    external = tmp_path / "external-session"
    external.mkdir()
    (external / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
    (external / f"{ACTIVE_HISTORY_FILENAME}.tmp").write_text("[]", encoding="utf-8")
    (external / BRANCH_TREE_FILENAME).write_text("{}", encoding="utf-8")
    unrelated = external / "important.txt"
    unrelated.write_text("keep", encoding="utf-8")

    remove_chat_history_storage(external)

    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert external.is_dir()
    assert not (external / ACTIVE_HISTORY_FILENAME).exists()
    assert not (external / BRANCH_TREE_FILENAME).exists()


def test_download_capability_is_file_bound(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text("[]", encoding="utf-8")
    second.write_text("[]", encoding="utf-8")
    state = _state(
        tmp_path,
        history_download_lock=threading.Lock(),
        history_download_capabilities={},
    )

    first_capability = _issue_chat_history_download_capability(state, first)
    assert _chat_history_download_file(state, first_capability) == first

    second_capability = _issue_chat_history_download_capability(state, second)
    with pytest.raises(PermissionError):
        _chat_history_download_file(state, first_capability)
    assert _chat_history_download_file(state, second_capability) == second


def test_download_route_uses_capability_not_main_bridge_token(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    history.write_text("[]", encoding="utf-8")
    state = _state(
        tmp_path,
        auth_token="main-write-token",
        history_download_lock=threading.Lock(),
        history_download_capabilities={},
    )
    capability = _issue_chat_history_download_capability(state, history)
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.path = f"/api/chat/history-file?cap={capability}"
    handler.headers = {}
    handler.server = SimpleNamespace(state=state)
    sent: list[Path] = []
    handler._send_local_file = lambda path, **_kwargs: sent.append(path)

    handler.do_GET()

    assert sent == [history]
    assert "main-write-token" not in handler.path


def test_external_history_copy_open_and_clear_commands(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external-session"
    external.mkdir()
    active = external / ACTIVE_HISTORY_FILENAME
    active.write_text(
        json.dumps([{"role": "user", "content": "hello"}]),
        encoding="utf-8",
    )
    (external / BRANCH_TREE_FILENAME).write_text("{}", encoding="utf-8")
    state = _state(
        project,
        chat_session={"historyPath": str(external), "sessionId": ""},
        chat_stream=None,
        history_download_lock=threading.Lock(),
        history_download_capabilities={},
    )

    with patch(
        "frontend_bridge_core.chat._chat_snapshot",
        side_effect=lambda _state, _status=None, _message="", *, extra=None: extra or {},
    ):
        copied = _handle_chat_command(state, {"type": "copy-history"})
        opened = _handle_chat_command(state, {"type": "open-history"})

    assert "hello" in copied["clipboardText"]
    capability = opened["downloadUrl"].split("cap=", 1)[1]
    assert _chat_history_download_file(state, capability) == external / BRANCH_TREE_FILENAME

    unrelated = external / "important.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with patch(
        "frontend_bridge_core.chat._chat_snapshot",
        side_effect=lambda _state, _status=None, _message="", *, extra=None: extra or {},
    ):
        _handle_chat_command(state, {"type": "clear-history"})
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not active.exists()


def test_non_file_runtime_command_does_not_resolve_stale_history_path() -> None:
    class Stream:
        def send_command(self, _session_id, _command):
            return True

        def get_snapshot(self, _session_id):
            return {"historyEntries": [], "status": "idle"}

        def update_session_snapshot(self, _session_id, _snapshot):
            return None

    state = _state(
        Path.cwd(),
        chat_session={
            "historyPath": r"C:offline\invalid.json",
            "sessionId": "session-1",
        },
        chat_stream=Stream(),
    )

    with patch("frontend_bridge_core.chat._chat_snapshot", return_value={"ok": True}):
        assert _handle_chat_command(state, {"type": "pause-asr"}) == {"ok": True}


def test_short_verbatim_project_root_is_regularized(tmp_path: Path) -> None:
    prepared = _prepare_project_root("\\\\?\\" + str(tmp_path), "--project-root")

    assert prepared == tmp_path.resolve(strict=True)
    assert not str(prepared).startswith("\\\\?\\")


def test_long_verbatim_history_path_keeps_prefix(tmp_path: Path) -> None:
    raw = "\\\\?\\" + str(tmp_path / Path(*(["long-directory-name"] * 20)) / "session.json")

    resolved = resolve_history_path_for_project(_state(tmp_path), raw)

    assert len(strip_windows_verbatim_prefix(str(resolved))) >= 248
    assert str(resolved).startswith("\\\\?\\")
    assert str(resolve_regular_path(raw)).startswith("\\\\?\\")


def test_long_verbatim_history_path_supports_real_io(tmp_path: Path) -> None:
    root = Path("\\\\?\\" + str(tmp_path))
    history = root.joinpath(*(["long-history-segment"] * 14), "session.json")
    assert len(strip_windows_verbatim_prefix(str(history))) >= 260
    history.parent.mkdir(parents=True)
    history.write_text("[]", encoding="utf-8")

    resolved = resolve_history_path_for_project(_state(tmp_path), history)

    assert str(resolved).startswith("\\\\?\\")
    assert resolved.read_text(encoding="utf-8") == "[]"
