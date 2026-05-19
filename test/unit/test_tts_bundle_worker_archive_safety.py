from __future__ import annotations

from types import SimpleNamespace

import pytest

from ui.settings_ui.tts import tts_bundle_worker as worker_mod


pytestmark = pytest.mark.unit


def _info(
    filename: str,
    *,
    compressed: int = 10,
    uncompressed: int = 10,
    is_directory: bool = False,
    is_file: bool = True,
    is_symlink: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        filename=filename,
        compressed=compressed,
        uncompressed=uncompressed,
        is_directory=is_directory,
        is_file=is_file,
        is_symlink=is_symlink,
    )


class _FakePy7zArchive:
    def __init__(self, infos):
        self._infos = infos

    def list(self):
        return self._infos


def test_tts_bundle_rejects_unsafe_bundle_dir_key() -> None:
    assert worker_mod._safe_bundle_dir_key("genie_tts_server") == "genie_tts_server"
    for raw in ("../escape", "nested/key", "/abs", "C:/escape"):
        with pytest.raises(ValueError, match="bundle_dir_key"):
            worker_mod._safe_bundle_dir_key(raw)


def test_tts_bundle_archive_member_validation_rejects_path_escape() -> None:
    with pytest.raises(ValueError, match="unsafe 7z member path"):
        worker_mod._validate_archive_member_names(["../escape.txt"])


def test_tts_bundle_py7zr_validation_rejects_symlink_and_zip_bomb_like_member() -> None:
    with pytest.raises(ValueError, match="unsupported 7z member type"):
        worker_mod._validate_py7zr_archive(
            _FakePy7zArchive([_info("link", is_file=False, is_symlink=True)])
        )

    with pytest.raises(ValueError, match="compression ratio"):
        worker_mod._validate_py7zr_archive(
            _FakePy7zArchive([_info("huge.bin", compressed=1, uncompressed=2000)])
        )


def test_tts_bundle_parse_7za_slt_paths_only_uses_file_section() -> None:
    stdout = """
Path = /tmp/archive.7z
Type = 7z
----------
Path = root/file.txt
Size = 2
Packed Size = 3
----------
Path = root/nested/model.bin
Size = 4
Packed Size = 5
"""

    assert worker_mod._parse_7za_slt_paths(stdout) == [
        "root/file.txt",
        "root/nested/model.bin",
    ]


def test_tts_bundle_7za_slt_validation_rejects_zip_bomb_like_entry() -> None:
    entries = worker_mod._parse_7za_slt_entries(
        """
Path = /tmp/archive.7z
Type = 7z
----------
Path = root/bomb.bin
Size = 2000
Packed Size = 1
Attributes = A
"""
    )

    with pytest.raises(ValueError, match="compression ratio"):
        worker_mod._validate_7za_entries(entries)


def test_tts_bundle_failed_extract_keeps_old_install_and_cleans_staging(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    final_dir = project / "data" / "tts_bundles" / "installed" / "genie_tts_server"
    final_dir.mkdir(parents=True)
    old_file = final_dir / "old.txt"
    old_file.write_text("old", encoding="utf-8")
    staging_dir = project / "data" / "tts_bundles" / "_extracting" / "genie_tts_server"

    class _FakeResponse:
        headers = {"Content-Length": "7"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _chunk_size):
            yield b"archive"

    class _BrokenSevenZipFile:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list(self):
            return [_info("root/file.txt")]

        def extract(self, *, path, targets):
            out = path / "partial.txt"
            out.write_text(str(targets), encoding="utf-8")
            raise RuntimeError("boom")

    monkeypatch.setattr(worker_mod.requests, "get", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(worker_mod, "_seven_zip_exe", lambda: None)
    monkeypatch.setattr(
        worker_mod,
        "_load_py7zr",
        lambda: SimpleNamespace(SevenZipFile=_BrokenSevenZipFile),
    )

    failures: list[str] = []
    worker = worker_mod.TtsBundleDownloadWorker(
        "https://example.invalid/bundle.7z",
        "genie_tts_server",
        project,
    )
    worker.failed.connect(failures.append)

    worker.run()

    assert failures and "extract: boom" in failures[-1]
    assert old_file.read_text(encoding="utf-8") == "old"
    assert not staging_dir.exists()
