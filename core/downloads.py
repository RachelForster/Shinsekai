"""Shared streaming archive download with cancellation and integrity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

import requests


class DownloadInterrupted(Exception):
    pass


def download_archive(
    url: str,
    archive: Path,
    headers: dict[str, str],
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    is_interrupted: Callable[[], bool] | None = None,
    on_progress: Callable[[int], None] | None = None,
    timeout: tuple[float, float] = (15, 600),
) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    part = archive.with_name(f"{archive.name}.part")
    part.unlink(missing_ok=True)
    try:
        hasher = hashlib.sha256() if expected_sha256 is not None else None
        with requests.get(
            url, stream=True, timeout=timeout, headers=headers
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0") or 0)
            if total <= 0 and expected_size is not None:
                total = expected_size
            size = 0
            with part.open("wb") as output:
                for chunk in response.iter_content(128 * 1024):
                    if is_interrupted is not None and is_interrupted():
                        raise DownloadInterrupted()
                    if not chunk:
                        continue
                    output.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    size += len(chunk)
                    if on_progress is not None:
                        on_progress(
                            min(70, int(70 * size / total))
                            if total > 0
                            else min(35, size // (10 * 1024 * 1024))
                        )
        if is_interrupted is not None and is_interrupted():
            raise DownloadInterrupted()
        if expected_size is not None and size != expected_size:
            raise ValueError(
                f"verification failed: size mismatch: expected {expected_size}, got {size}"
            )
        if hasher is not None and hasher.hexdigest().lower() != expected_sha256.lower():
            raise ValueError(
                "verification failed: sha256 mismatch: expected "
                f"{expected_sha256}, got {hasher.hexdigest()}"
            )
        part.replace(archive)
    except requests.exceptions.ReadTimeout:
        part.unlink(missing_ok=True)
        if is_interrupted is not None and is_interrupted():
            raise DownloadInterrupted()
        raise
    except Exception:
        part.unlink(missing_ok=True)
        raise
