import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from application.story import deletion_transaction as transaction


@pytest.fixture
def files(tmp_path):
    # Include an external registered history as well as the source and metadata.
    paths = [tmp_path / name for name in (
        "data/stories/story.json", "external/history/active.json", "config/conversations/chat.json",
    )]
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"original {index}".encode())
    return paths


@pytest.mark.parametrize("failure", ["copy", "flush"])
def test_backup_failure_never_enters_deletion(tmp_path, files, monkeypatch, failure):
    originals = {path: path.read_bytes() for path in files}
    recovery = tmp_path / "recovery"

    def fail(*args, **kwargs):
        raise OSError("disk full")

    if failure == "copy":
        monkeypatch.setattr(ZipFile, "write", fail)
    else:
        monkeypatch.setattr(transaction.os, "fsync", fail)
    with pytest.raises(OSError, match="disk full"):
        with transaction.recoverable_deletion(files, recovery):
            pytest.fail("must finish backing up before deleting")
    assert {path: path.read_bytes() for path in files} == originals
    assert not list(recovery.iterdir())


def test_locked_commit_archive_rolls_back_source_and_external_history(tmp_path, files, monkeypatch):
    originals = {path: path.read_bytes() for path in files}
    modified = {path: path.stat().st_mtime_ns for path in files}
    recovery = tmp_path / "recovery"
    unlink = Path.unlink

    def fail_commit(path, *args, **kwargs):
        if path.parent == recovery:
            raise PermissionError("recovery archive is locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_commit)
    with pytest.raises(PermissionError, match="locked"):
        with transaction.recoverable_deletion(files, recovery):
            for path in files:
                path.unlink()
    assert {path: path.read_bytes() for path in files} == originals
    assert {path: path.stat().st_mtime_ns for path in files} == modified
    assert len(list(recovery.glob("*.zip"))) == 1


def test_failed_rollback_preserves_complete_archive_for_explicit_recovery(tmp_path, files, monkeypatch):
    originals = {path: path.read_bytes() for path in files}
    recovery = tmp_path / "recovery"
    rename = transaction.durable_rename

    def fail_one_restore(temporary, destination):
        if destination == files[1]:
            raise PermissionError("external directory is locked")
        return rename(temporary, destination)

    with monkeypatch.context() as patch:
        patch.setattr(transaction, "durable_rename", fail_one_restore)
        with pytest.raises(RuntimeError, match="完整恢复副本保留在") as error:
            with transaction.recoverable_deletion(files, recovery):
                for path in files:
                    path.unlink()
                    path.parent.rmdir()
                raise OSError("later deletion failed")

    backup, = recovery.glob("*.zip")
    assert str(backup) in str(error.value)
    # Recovery attempts continue after a failure rather than losing later files.
    assert files[0].read_bytes() == originals[files[0]]
    assert not files[1].exists()
    assert files[2].read_bytes() == originals[files[2]]
    with ZipFile(backup) as archive:
        entries = json.loads(archive.read("manifest.json"))
        assert {Path(item["path"]): archive.read(item["entry"]) for item in entries} == originals

    transaction.restore_deletion(backup)
    assert {path: path.read_bytes() for path in files} == originals
    assert backup.exists()  # Only remove the recovery copy after verifying recovery.


def test_success_commits_only_owned_files_and_removes_recovery_copy(tmp_path, files):
    recovery = tmp_path / "recovery"
    unrelated = files[1].with_name("notes.txt")
    unrelated.write_bytes(b"keep me")
    with transaction.recoverable_deletion([*files, files[0], tmp_path / "missing"], recovery):
        for path in files:
            path.unlink()
    assert all(not path.exists() for path in files)
    assert unrelated.read_bytes() == b"keep me"
    assert not list(recovery.iterdir())
