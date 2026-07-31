from __future__ import annotations

import pytest

from core.media import snapshots as media_snapshots


def test_runtime_media_snapshot_reads_exact_bytes_without_cwd_lookup(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    media = project / "data" / "audio" / "声音.ogg"
    media.parent.mkdir(parents=True)
    unrelated.mkdir()
    media.write_bytes(b"approved-media")
    monkeypatch.chdir(unrelated)

    snapshot = media_snapshots.capture_runtime_media(
        "data/audio/声音.ogg",
        root=project,
    )

    assert snapshot.path == media
    assert snapshot.payload == b"approved-media"


def test_runtime_media_snapshot_rejects_linked_input(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external.ogg"
    alias = project / "data" / "audio" / "alias.ogg"
    alias.parent.mkdir(parents=True)
    external.write_bytes(b"external")
    try:
        alias.symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        media_snapshots.capture_runtime_media(
            "data/audio/alias.ogg",
            root=project,
        )


def test_runtime_media_snapshot_rejects_parent_replacement_after_read(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    media_parent = project / "data" / "audio"
    preserved_parent = project / "data" / "preserved-audio"
    media = media_parent / "voice.wav"
    media_parent.mkdir(parents=True)
    media.write_bytes(b"approved")
    real_read = media_snapshots.read_bytes_snapshot_without_links

    def replace_parent(path, **kwargs):
        result = real_read(path, **kwargs)
        media_parent.rename(preserved_parent)
        media_parent.mkdir()
        (media_parent / "voice.wav").write_bytes(b"replacement")
        return result

    monkeypatch.setattr(
        media_snapshots,
        "read_bytes_snapshot_without_links",
        replace_parent,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        media_snapshots.capture_runtime_media(
            "data/audio/voice.wav",
            root=project,
        )
