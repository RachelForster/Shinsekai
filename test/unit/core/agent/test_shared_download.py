import hashlib

import pytest

import core.downloads as module


class Response:
    headers = {"Content-Length": "4"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield b"data"


@pytest.mark.parametrize("mode", ["checksum", "cancel", "size"])
def test_failed_download_preserves_previous_archive(monkeypatch, tmp_path, mode):
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"previous")
    with pytest.raises((ValueError, module.DownloadInterrupted)):
        module.download_archive(
            "https://example.com/archive",
            archive,
            {},
            expected_sha256=(
                "wrong" if mode == "checksum" else hashlib.sha256(b"data").hexdigest()
            ),
            expected_size=5 if mode == "size" else 4,
            is_interrupted=lambda: mode == "cancel",
        )
    assert archive.read_bytes() == b"previous"
    assert not archive.with_name("archive.zip.part").exists()


def test_tts_keeps_the_shared_download_entry_point():
    from core.model_assets.tts_bundle_archive import (
        _download_archive,
        _DownloadInterrupted,
    )

    assert _download_archive is module.download_archive
    assert _DownloadInterrupted is module.DownloadInterrupted
