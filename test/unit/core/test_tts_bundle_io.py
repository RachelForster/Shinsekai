from __future__ import annotations

from pathlib import Path
import hashlib
import json

import pytest

from core import tts_bundle_catalog, tts_bundle_io


class _Response:
    def __init__(
        self,
        payload: bytes,
        *,
        url: str = "https://example.invalid/bundle.7z",
    ) -> None:
        self._payload = payload
        self.url = url
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, _chunk_size: int):
        yield self._payload


def test_tts_download_verifies_staging_before_replacing_existing_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "bundle.7z"
    archive.write_bytes(b"previous")
    monkeypatch.setattr(
        tts_bundle_io.requests,
        "get",
        lambda *_args, **_kwargs: _Response(b"replacement"),
    )

    with pytest.raises(ValueError, match="sha256 mismatch"):
        tts_bundle_io._download_archive(
            "https://example.invalid/bundle.7z",
            archive,
            {},
            expected_size=len(b"replacement"),
            expected_sha256="0" * 64,
        )

    assert archive.read_bytes() == b"previous"
    assert list(tmp_path.glob(".bundle.7z.*.tmp")) == []


def test_tts_download_rejects_credentialed_redirect_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "bundle.7z"
    monkeypatch.setattr(
        tts_bundle_io.requests,
        "get",
        lambda *_args, **_kwargs: _Response(
            b"bundle",
            url="https://token@example.invalid/bundle.7z",
        ),
    )

    with pytest.raises(ValueError, match="credentials"):
        tts_bundle_io._download_archive(
            "https://example.invalid/bundle.7z",
            archive,
            {},
        )

    assert not archive.exists()


@pytest.mark.parametrize(
    "url",
    (
        "file:///tmp/bundle.7z",
        "https://example.invalid/%2e%2e",
        "https://example.invalid/CON",
    ),
)
def test_tts_archive_filename_rejects_nonportable_urls(url: str) -> None:
    with pytest.raises(ValueError):
        tts_bundle_io._archive_filename(url)


@pytest.mark.parametrize(
    "url",
    (
        "https://example.invalid/a%2Fb.7z",
        "https://example.invalid/a%5Cb.7z",
        "https://example.invalid/bundle%ZZ.7z",
        "https://example.invalid/bundle%FF.7z",
    ),
)
def test_tts_archive_filename_rejects_ambiguous_encoded_components(
    url: str,
) -> None:
    with pytest.raises(ValueError):
        tts_bundle_io._archive_filename(url)


def test_tts_archive_filename_strictly_decodes_one_utf8_component() -> None:
    assert (
        tts_bundle_io._archive_filename(
            "https://example.invalid/releases/%E6%96%B0%E4%B8%96%E7%95%8C.7z"
        )
        == "新世界.7z"
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://example.invalid:invalid/bundle.7z",
        "https://example.invalid:99999/bundle.7z",
        "https://exa mple.invalid/bundle.7z",
        "https://%65xample.invalid/bundle.7z",
        "https://example.invalid\\@other.invalid/bundle.7z",
    ),
)
def test_tts_catalog_and_downloader_share_strict_url_authority_contract(
    url: str,
) -> None:
    with pytest.raises(ValueError):
        tts_bundle_catalog._validated_download_url(url)
    with pytest.raises(ValueError):
        tts_bundle_io._validated_download_url(url)


@pytest.mark.parametrize(
    ("first_key", "second_key", "first_filename", "second_filename"),
    (
        ("Bundle", "bundle", "first.7z", "second.7z"),
        ("caf\u00e9", "cafe\u0301", "first.7z", "second.7z"),
        ("first", "second", "CAF\u00c9.7z", "cafe\u0301.7z"),
    ),
)
def test_tts_manifest_rejects_portable_path_name_collisions(
    tmp_path: Path,
    first_key: str,
    second_key: str,
    first_filename: str,
    second_filename: str,
) -> None:
    payload = b"bundle"
    digest = hashlib.sha256(payload).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bundles": [
                    {
                        "kind": "first",
                        "bundle_dir_key": first_key,
                        "filename": first_filename,
                        "download_url": "https://example.invalid/first.7z",
                        "size": len(payload),
                        "sha256": digest,
                    },
                    {
                        "kind": "second",
                        "bundle_dir_key": second_key,
                        "filename": second_filename,
                        "download_url": "https://example.invalid/second.7z",
                        "size": len(payload),
                        "sha256": digest,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate TTS bundle"):
        tts_bundle_catalog.load_tts_bundle_manifest(manifest_path)
