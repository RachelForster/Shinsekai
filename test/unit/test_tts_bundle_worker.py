import hashlib
from pathlib import Path

import pytest

from ui.settings_ui.tts import tts_bundle_worker as worker_mod
from ui.settings_ui.tts.tts_bundle_manifest import TtsBundleManifestEntry


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield self._payload[:2]
        yield b""
        yield self._payload[2:]


def _manifest_for_payload(payload: bytes) -> TtsBundleManifestEntry:
    return TtsBundleManifestEntry(
        kind="demo",
        bundle_dir_key="demo_bundle",
        filename="demo.7z",
        download_url="https://example.test/demo.7z",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _patch_extract_success(monkeypatch, extracted_roots: list[Path]) -> None:
    def fake_extract(_exe: Path, _archive: Path, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        extracted_roots.append(out_dir)
        return None

    monkeypatch.setattr(worker_mod, "_load_py7zr", lambda: None)
    monkeypatch.setattr(worker_mod, "_seven_zip_exe", lambda: Path("/bin/7za"))
    monkeypatch.setattr(worker_mod, "_extract_7za", fake_extract)


def test_archive_verification_accepts_matching_file(tmp_path):
    payload = b"bundle-content"
    manifest = _manifest_for_payload(payload)
    archive = tmp_path / manifest.filename
    archive.write_bytes(payload)

    assert worker_mod._archive_verification_error(archive, manifest) is None


def test_archive_verification_rejects_wrong_hash(tmp_path):
    payload = b"bundle-content"
    manifest = _manifest_for_payload(payload)
    archive = tmp_path / manifest.filename
    archive.write_bytes(b"Bundle-content")

    assert "sha256 mismatch" in worker_mod._archive_verification_error(
        archive, manifest
    )


def test_download_archive_writes_part_then_replaces_target(tmp_path, monkeypatch):
    payload = b"fresh-bundle"
    archive = tmp_path / "demo.7z"
    progress: list[int] = []

    monkeypatch.setattr(
        worker_mod.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(payload),
    )

    worker_mod._download_archive(
        "https://example.test/demo.7z",
        archive,
        {},
        expected_size=len(payload),
        on_progress=progress.append,
    )

    assert archive.read_bytes() == payload
    assert not archive.with_name("demo.7z.part").exists()
    assert progress[-1] == 70


def test_worker_reuses_verified_download_without_request(tmp_path, monkeypatch):
    payload = b"cached-bundle"
    manifest = _manifest_for_payload(payload)
    archive = tmp_path / "data" / "tts_bundles" / "downloads" / manifest.filename
    archive.parent.mkdir(parents=True)
    archive.write_bytes(payload)
    extracted_roots: list[Path] = []

    monkeypatch.setattr(worker_mod, "bundle_manifest_for_key", lambda _key: manifest)
    monkeypatch.setattr(
        worker_mod.requests,
        "get",
        lambda *args, **kwargs: pytest.fail("cache hit should not download"),
    )
    _patch_extract_success(monkeypatch, extracted_roots)

    statuses: list[str] = []
    finished: list[str] = []
    w = worker_mod.TtsBundleDownloadWorker(
        manifest.download_url,
        manifest.bundle_dir_key,
        tmp_path,
    )
    w.status.connect(statuses.append)
    w.finished_ok.connect(finished.append)

    w.run()

    assert statuses == ["verify", "extract"]
    assert extracted_roots == [
        tmp_path / "data" / "tts_bundles" / "installed" / "demo_bundle"
    ]
    assert finished


def test_worker_redownloads_and_verifies_invalid_cache(tmp_path, monkeypatch):
    payload = b"fresh-bundle"
    manifest = _manifest_for_payload(payload)
    archive = tmp_path / "data" / "tts_bundles" / "downloads" / manifest.filename
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"bad")
    extracted_roots: list[Path] = []
    requests_made: list[str] = []

    monkeypatch.setattr(worker_mod, "bundle_manifest_for_key", lambda _key: manifest)
    monkeypatch.setattr(
        worker_mod.requests,
        "get",
        lambda url, *args, **kwargs: requests_made.append(url)
        or _FakeResponse(payload),
    )
    _patch_extract_success(monkeypatch, extracted_roots)

    statuses: list[str] = []
    finished: list[str] = []
    w = worker_mod.TtsBundleDownloadWorker(
        manifest.download_url,
        manifest.bundle_dir_key,
        tmp_path,
    )
    w.status.connect(statuses.append)
    w.finished_ok.connect(finished.append)

    w.run()

    assert archive.read_bytes() == payload
    assert requests_made == [manifest.download_url]
    assert statuses == ["verify", "download", "verify", "extract"]
    assert extracted_roots
    assert finished
