"""Dependency-free durable filesystem publication shared across host layers."""

from __future__ import annotations

import os
from pathlib import Path


def sync_directory(directory: Path) -> None:
    """Persist directory entries on POSIX; Windows publication uses write-through."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_mkdir(directory: Path) -> None:
    """Create parents and persist each new directory's entry before publication."""
    missing = []
    ancestor = directory
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    directory.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        sync_directory(created.parent)


def durable_rename(temporary: Path, destination: Path, *, replace: bool = False) -> None:
    """Publish an already-fsynced sibling file and persist the directory entry.

    On POSIX, failure may occur *after* the rename, during directory fsync.
    Callers must retain dependencies if the published destination is visible.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        # MOVEFILE_WRITE_THROUGH, plus REPLACE_EXISTING for mutable manifests.
        flags = 0x8 | (0x1 if replace else 0)
        if not move(str(temporary), str(destination), flags):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(temporary, destination)
        sync_directory(destination.parent)
