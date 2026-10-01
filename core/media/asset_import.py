"""Lease-protected immutable batches; configuration references publish them."""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Callable

from filelock import FileLock, Timeout

from sdk.path_utils import safe_child_path


logger = logging.getLogger(__name__)
PENDING_MARKER = ".pending-import"
_BATCH_NAME = re.compile(r"\.batch-[0-9a-f]{32}\Z")


def _batch_path(parent: Path, name: str) -> Path:
    if not _BATCH_NAME.fullmatch(name):
        raise ValueError("Invalid managed import batch name")
    parent = parent.resolve(strict=True)
    candidate = safe_child_path(parent, name)
    if candidate != parent / name:
        raise ValueError("Import batch must not redirect to another directory")
    return candidate


class PendingAssetBatch:
    """Copy once into a hidden namespace, holding an OS-backed recovery lease.

    Call commit only after the configuration write succeeds. Unexpected process
    exit leaves the marker/lease file; the OS releases the lease automatically.
    No paths from a marker are ever used as recursive deletion targets.
    """

    def __init__(self, parent: Path):
        parent.mkdir(parents=True, exist_ok=True)
        self.path = _batch_path(parent, f".batch-{uuid.uuid4().hex}")
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.lease = FileLock(str(self.lock_path))
        self.committed = False

    def __enter__(self):
        self.lease.acquire()
        try:
            self.path.mkdir()
            with (self.path / PENDING_MARKER).open("xb") as handle:
                handle.write(b"avatar-state-import-v1\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def commit(self) -> None:
        self.committed = True

    def __exit__(self, error_type, error, traceback):
        try:
            if self.committed:
                # Cleanup failure after config commit is not a rollback signal.
                try:
                    (self.path / PENDING_MARKER).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Committed import marker will be recovered: %s", self.path, exc_info=True)
            elif error_type is None or issubclass(error_type, Exception):
                checked = _batch_path(self.path.parent, self.path.name)
                if checked.is_dir():
                    shutil.rmtree(checked)
            # BaseException stands in for abrupt exit: retain the durable marker.
        finally:
            self.lease.release()
            if self.committed or not self.path.exists():
                try:
                    self.lock_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Import lease file could not be removed: %s", self.lock_path, exc_info=True)


def recover_asset_batches(parent: Path, is_referenced: Callable[[Path], bool]) -> None:
    """Remove marked, uncommitted batches; leave active or referenced ones alone."""
    if not parent.is_dir():
        return
    for candidate in parent.glob(".batch-*"):
        if not _BATCH_NAME.fullmatch(candidate.name):
            continue
        lock_path = candidate.with_name(f"{candidate.name}.lock")
        try:
            checked = _batch_path(parent, candidate.name)
            if not checked.is_dir():
                continue
            with FileLock(str(lock_path), timeout=0):
                marker = checked / PENDING_MARKER
                if not marker.exists():
                    # Committed batches have no marker. An empty directory may
                    # be left by an exit between mkdir and marker creation.
                    if not any(checked.iterdir()):
                        checked.rmdir()
                elif is_referenced(checked):
                    marker.unlink()
                else:
                    shutil.rmtree(checked)
                    logger.info("Recovered uncommitted avatar import: %s", checked)
            lock_path.unlink(missing_ok=True)
        except Timeout:
            continue  # A concurrent import still owns its OS lease.
        except Exception:
            logger.warning("Avatar import recovery deferred: %s", candidate, exc_info=True)


def ignore_pending_batches(directory: str, names: list[str]) -> list[str]:
    """Never export partially prepared batches or their lease files."""
    parent = Path(directory)
    return [name for name in names if (
        (_BATCH_NAME.fullmatch(name) and (parent / name / PENDING_MARKER).exists())
        or (name.endswith(".lock") and _BATCH_NAME.fullmatch(name[:-5]))
    )]
