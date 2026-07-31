"""Stable byte snapshots for local media consumers.

Qt and pygame accept path strings and reopen those paths internally.  A path
that was validated by Python can therefore name a different object by the
time the decoder runs.  Read the selected file once through the no-follow
descriptor contract and hand decoders the resulting bytes instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.file_transactions import (
    capture_directory_identity,
    file_snapshot_is_stable,
    read_bytes_snapshot_without_links,
    require_directory_identity,
)
from core.paths import project_root, resolve_runtime_asset_read_path


@dataclass(frozen=True)
class RuntimeMediaSnapshot:
    path: Path
    payload: bytes
    identity: os.stat_result
    parent_identity: os.stat_result

    def is_same_content(self, other: "RuntimeMediaSnapshot | None") -> bool:
        return other is not None and file_snapshot_is_stable(
            self.identity,
            other.identity,
        )


def capture_runtime_media(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
) -> RuntimeMediaSnapshot:
    """Capture one exact runtime-media file and its immutable byte payload."""

    selected_root = project_root() if root is None else root
    path = resolve_runtime_asset_read_path(value, root=selected_root)
    parent, parent_identity = capture_directory_identity(
        path.parent,
        field="runtime media parent directory",
    )
    payload, identity = read_bytes_snapshot_without_links(
        path,
        expected_parent_identity=parent_identity,
    )
    require_directory_identity(
        parent,
        parent_identity,
        field="runtime media parent directory",
    )
    return RuntimeMediaSnapshot(
        path=path,
        payload=payload,
        identity=identity,
        parent_identity=parent_identity,
    )


def qimage_from_snapshot(snapshot: RuntimeMediaSnapshot):
    """Decode a snapshot without letting Qt reopen its public pathname."""

    from PySide6.QtGui import QImage

    image = QImage()
    image.loadFromData(snapshot.payload)
    return image


def qpixmap_from_snapshot(snapshot: RuntimeMediaSnapshot):
    """Decode a snapshot without letting Qt reopen its public pathname."""

    from PySide6.QtGui import QPixmap

    pixmap = QPixmap()
    pixmap.loadFromData(snapshot.payload)
    return pixmap


def load_qpixmap_without_links(
    value: str | os.PathLike[str],
    *,
    root: str | Path | None = None,
):
    return qpixmap_from_snapshot(capture_runtime_media(value, root=root))
