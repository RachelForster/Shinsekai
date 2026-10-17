from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import ctypes
import pytest

from sdk import file_io


@pytest.mark.parametrize("replace, flags", [(False, 0x8), (True, 0x9)])
def test_windows_rename_is_write_through_and_optionally_replaces(monkeypatch, replace, flags):
    move = Mock(return_value=1)
    dll = Mock(return_value=SimpleNamespace(MoveFileExW=move))
    monkeypatch.setattr(file_io, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "WinDLL", dll, raising=False)
    source, destination = Path("temporary.json"), Path("current.json")
    file_io.durable_rename(source, destination, replace=replace)
    dll.assert_called_once_with("kernel32", use_last_error=True)
    move.assert_called_once_with(str(source), str(destination), flags)


def test_windows_rename_failure_propagates(monkeypatch):
    monkeypatch.setattr(file_io, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=SimpleNamespace(MoveFileExW=Mock(return_value=0))), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    error = PermissionError("write-through rename denied")
    monkeypatch.setattr(ctypes, "WinError", lambda code: error if code == 5 else AssertionError(code), raising=False)
    with pytest.raises(PermissionError, match="write-through"):
        file_io.durable_rename(Path("temporary.json"), Path("current.json"), replace=True)


@pytest.mark.parametrize("fail_sync", [False, True])
def test_posix_rename_syncs_parent_and_closes_descriptor_even_on_failure(monkeypatch, fail_sync):
    events = Mock()
    events.open.return_value = 42
    if fail_sync:
        events.fsync.side_effect = OSError("directory sync failed")
    monkeypatch.setattr(file_io, "os", SimpleNamespace(
        name="posix", O_RDONLY=0, O_DIRECTORY=16,
        replace=events.replace, open=events.open, fsync=events.fsync, close=events.close,
    ))
    source, destination = Path("temporary.json"), Path("runtime/current.json")
    if fail_sync:
        with pytest.raises(OSError, match="directory sync failed"):
            file_io.durable_rename(source, destination, replace=True)
    else:
        file_io.durable_rename(source, destination, replace=True)
    assert events.mock_calls == [
        call.replace(source, destination), call.open(destination.parent, 16), call.fsync(42), call.close(42),
    ]


def test_new_directory_ancestors_are_synced_and_existing_ones_are_not(tmp_path, monkeypatch):
    sync = Mock()
    monkeypatch.setattr(file_io, "sync_directory", sync)
    root = tmp_path / "runtime/avatars/l2d"
    file_io.durable_mkdir(root)
    assert root.is_dir()
    assert sync.call_args_list == [call(tmp_path), call(tmp_path / "runtime"), call(tmp_path / "runtime/avatars")]
    sync.reset_mock()
    file_io.durable_mkdir(root)
    sync.assert_not_called()
