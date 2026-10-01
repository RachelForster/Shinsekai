"""Pinned user-supplied Cubism SDK input. Never download or redistribute the SDK."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from pathlib import Path, PurePosixPath

from sdk.adapters.avatar import ModelRuntimeInstaller

SDK_SHA256 = "d78904d908bd232b800219e01732e4ea2f0562b5e9f35a2670742a1c16d22942"
# Deterministic output of our bridge + TypeScript 5.9.3, checked with the official ZIP.
COMPILED_SHA256 = "1eed52ae04123efa8b482f435807e9f566f00c9459ff0259c002c4f33628a565"
SDK_ROOT = "CubismSdkForWeb-5-r.4/"
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024


def _inputs(source: Path) -> dict[str, bytes]:
    try:
        if not source.is_file() or source.suffix.lower() != ".zip":
            raise ValueError("Select the original Cubism SDK for Web 5-r.4 ZIP")
        with source.open("rb") as handle:
            if source.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("SDK ZIP exceeds 256 MiB")
            content = handle.read(MAX_ARCHIVE_BYTES + 1)
        if len(content) > MAX_ARCHIVE_BYTES:
            raise ValueError("SDK ZIP exceeds 256 MiB")
        if hashlib.sha256(content).hexdigest() != SDK_SHA256:
            raise ValueError("Expected the unmodified official Cubism SDK for Web 5-r.4 ZIP (use Older Versions)")
        # Parse the exact bytes hashed above, not a reopened/possibly replaced path.
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            result: dict[str, bytes] = {}
            total = 0
            for entry in archive.infolist():
                path = PurePosixPath(entry.orig_filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.orig_filename or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Unsafe SDK ZIP entry")
                if not entry.filename.startswith(SDK_ROOT) or entry.is_dir():
                    continue
                relative = entry.filename[len(SDK_ROOT):]
                selected = relative in {"Core/live2dcubismcore.min.js", "Core/LICENSE.md", "Framework/LICENSE.md"} or (
                    relative.startswith("Framework/src/") and relative.endswith(".ts") and not relative.endswith(".d.ts")
                )
                if not selected:
                    continue
                total += entry.file_size
                if total > MAX_INPUT_BYTES or entry.file_size > 2 * 1024 * 1024 or relative in result:
                    raise ValueError("Invalid or oversized SDK inputs")
                result[relative] = archive.read(entry)
            required = {"Core/live2dcubismcore.min.js", "Core/LICENSE.md", "Framework/LICENSE.md", "Framework/src/live2dcubismframework.ts"}
            if not required.issubset(result):
                raise ValueError("SDK ZIP is incomplete")
            return result
    except (OSError, zipfile.BadZipFile, UnicodeError) as error:
        raise ValueError("Cannot read the SDK ZIP") from error


class Live2DRuntimeInstaller(ModelRuntimeInstaller):
    version = "5-r.4"
    download_url = "https://www.live2d.com/en/sdk/download/web/"
    license_urls = (
        "https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html",
        "https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html",
    )
    filenames = ("live2dcubismcore.min.js", "cubism-sdk.js", "cubism-core-LICENSE.md", "cubism-framework-LICENSE.md")

    def prepare(self, source: Path) -> dict:
        return {"sources": {name: value.decode("utf-8-sig") for name, value in _inputs(source).items() if name.endswith(".ts")}}

    def files(self, source: Path, compiled: str) -> dict[str, bytes]:
        if not isinstance(compiled, str) or len(compiled) > MAX_INPUT_BYTES:
            raise ValueError("Invalid compiled SDK")
        bundle = compiled.encode("utf-8")
        if hashlib.sha256(bundle).hexdigest() != COMPILED_SHA256:
            raise ValueError("Compiled SDK failed integrity verification")
        inputs = _inputs(source)
        return {
            "live2dcubismcore.min.js": inputs["Core/live2dcubismcore.min.js"],
            "cubism-sdk.js": bundle,
            "cubism-core-LICENSE.md": inputs["Core/LICENSE.md"],
            "cubism-framework-LICENSE.md": inputs["Framework/LICENSE.md"],
        }
