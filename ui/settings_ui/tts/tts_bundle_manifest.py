"""Load the built-in manifest for downloadable TTS bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TtsBundleManifestEntry:
    kind: str
    bundle_dir_key: str
    filename: str
    download_url: str
    size: int
    sha256: str


def _manifest_path() -> Path:
    return Path(__file__).with_name("tts_bundle_manifest.json")


def _entry_from_dict(raw: dict[str, Any]) -> TtsBundleManifestEntry:
    return TtsBundleManifestEntry(
        kind=str(raw["kind"]),
        bundle_dir_key=str(raw["bundle_dir_key"]),
        filename=str(raw["filename"]),
        download_url=str(raw["download_url"]),
        size=int(raw["size"]),
        sha256=str(raw["sha256"]).lower(),
    )


def load_tts_bundle_manifest(
    path: Path | None = None,
) -> dict[str, TtsBundleManifestEntry]:
    src = path or _manifest_path()
    with src.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    entries = [_entry_from_dict(raw) for raw in payload.get("bundles", [])]
    return {entry.kind: entry for entry in entries}


TTS_BUNDLE_MANIFEST = load_tts_bundle_manifest()

_TTS_BUNDLE_MANIFEST_BY_KEY = {
    entry.bundle_dir_key: entry for entry in TTS_BUNDLE_MANIFEST.values()
}
URL_GENIE = TTS_BUNDLE_MANIFEST["genie"].download_url
URL_GPTSOVITS_STANDARD = TTS_BUNDLE_MANIFEST["gptso"].download_url
URL_GPTSOVITS_NVIDIA50 = TTS_BUNDLE_MANIFEST["gptso50"].download_url


def bundle_manifest_for_kind(kind: str) -> TtsBundleManifestEntry | None:
    return TTS_BUNDLE_MANIFEST.get(kind)


def bundle_manifest_for_key(bundle_dir_key: str) -> TtsBundleManifestEntry | None:
    return _TTS_BUNDLE_MANIFEST_BY_KEY.get(bundle_dir_key)
