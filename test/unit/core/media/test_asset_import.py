import subprocess
import sys
from pathlib import Path

import pytest

from core.media.asset_import import PendingAssetBatch, PENDING_MARKER, recover_asset_batches


def test_os_exit_leaves_recoverable_batch_and_releases_process_lease(tmp_path):
    script = """
import os, sys
from pathlib import Path
from core.media.asset_import import PendingAssetBatch
with PendingAssetBatch(Path(sys.argv[1])) as batch:
    (batch.path / 'partial.vmd').write_bytes(b'partial')
    os._exit(23)
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], timeout=20)
    assert result.returncode == 23
    batch = next(tmp_path.glob(f".batch-*/{PENDING_MARKER}")).parent
    recover_asset_batches(tmp_path, lambda path: False)
    assert not batch.exists()
    assert list(tmp_path.iterdir()) == []


def test_recovery_does_not_touch_concurrent_import(tmp_path):
    with PendingAssetBatch(tmp_path) as transaction:
        (transaction.path / "pose.vpd").write_bytes(b"staged")
        def unexpected(path):
            pytest.fail("Recovery acquired an active batch lease")
        recover_asset_batches(tmp_path, unexpected)
        assert (transaction.path / "pose.vpd").is_file()
        assert (transaction.path / PENDING_MARKER).is_file()
    assert list(tmp_path.iterdir()) == []


def test_committed_batches_are_retained_and_recovery_errors_are_deferred(tmp_path):
    with PendingAssetBatch(tmp_path) as transaction:
        (transaction.path / "pose.vpd").write_bytes(b"committed")
        transaction.commit()
    recover_asset_batches(tmp_path, lambda path: False)
    assert (transaction.path / "pose.vpd").is_file()
    assert not (transaction.path / PENDING_MARKER).exists()
    # Unknown commit status must never be interpreted as permission to delete.
    marker = transaction.path / PENDING_MARKER
    marker.write_text("pending")
    recover_asset_batches(tmp_path, lambda path: (_ for _ in ()).throw(RuntimeError("config unreadable")))
    assert marker.is_file()
    assert (transaction.path / "pose.vpd").is_file()


def test_recovery_cannot_follow_batch_symlink_outside_managed_root(tmp_path):
    parent = tmp_path / "managed"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / PENDING_MARKER).touch()
    secret = outside / "keep.txt"
    secret.write_text("keep")
    link = parent / (".batch-" + "a" * 32)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    recover_asset_batches(parent, lambda path: False)
    assert secret.read_text() == "keep"
