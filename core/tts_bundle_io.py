"""Identity-bound download, extraction, and publication of TTS bundles."""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit

import requests

from sdk.archive_paths import validate_archive_member_names
from sdk.file_transactions import (
    atomic_binary_writer,
    capture_directory_identity,
    clear_directory_without_links,
    file_snapshot_is_stable,
    inspect_portable_directory_tree,
    open_binary_read_without_links,
    remove_directory_without_links,
    replace_directory_transactionally,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from core.paths import (
    _metadata_is_link_or_reparse_point,
    app_root,
    managed_child_path,
    managed_project_storage,
    require_directory_without_links,
    safe_path_component,
    source_root,
)
from sdk.process_launch import (
    LaunchDirectorySnapshot,
    LaunchFileSnapshot,
    capture_command_executable,
    capture_launch_directory,
    capture_launch_file,
    popen_with_stable_paths,
    require_launch_snapshots,
)
from core.tts_bundle_catalog import (
    TtsBundleManifestEntry,
    _validated_download_url,
)

_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_DOWNLOAD_CHUNK_SIZE = 128 * 1024
_HASH_CHUNK_SIZE = 4 * 1024 * 1024
_SEVEN_ZIP_COMMANDS = (
    "7zz.exe",
    "7za.exe",
    "7z.exe",
    "7zz",
    "7za",
    "7z",
)

_BUNDLE_IO_LOCK = threading.RLock()
_ENCODED_PATH_SEPARATOR_RE = re.compile(r"%(?:2f|5c)", re.IGNORECASE)
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class _DownloadInterrupted(Exception):
    pass


class _ExtractionInterrupted(Exception):
    pass


def _archive_filename(url: str) -> str:
    parsed = urlsplit(_validated_download_url(url))
    encoded_name = parsed.path.rsplit("/", 1)[-1]
    if not encoded_name:
        return "bundle.7z"
    if (
        _ENCODED_PATH_SEPARATOR_RE.search(encoded_name)
        or _INVALID_PERCENT_ESCAPE_RE.search(encoded_name)
    ):
        raise ValueError("TTS archive filename contains ambiguous URL encoding")
    try:
        filename = unquote_to_bytes(encoded_name).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("TTS archive filename contains invalid UTF-8") from exc
    return safe_path_component(filename, field="TTS archive filename")


def _bundle_storage_paths(
    project_root: Path,
    bundle_dir_key: str,
) -> tuple[Path, Path]:
    downloads = managed_project_storage(
        "data/tts_bundles/downloads",
        root=project_root,
    )
    installed = managed_project_storage(
        "data/tts_bundles/installed",
        root=project_root,
    )
    destination = managed_child_path(
        installed,
        safe_path_component(
            bundle_dir_key,
            field="TTS bundle directory key",
        ),
        field="TTS bundle directory",
    )
    return downloads, destination


def _archive_verification_error(
    archive: Path,
    manifest: TtsBundleManifestEntry,
    *,
    is_interrupted: Any | None = None,
) -> str | None:
    try:
        metadata = archive.lstat()
    except FileNotFoundError:
        return "archive is missing"
    if (
        _metadata_is_link_or_reparse_point(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise PermissionError(f"TTS archive must be a regular file: {archive}")

    parent, parent_identity = capture_directory_identity(
        archive.parent,
        field="TTS archive directory",
    )
    if archive.parent != parent:
        raise PermissionError("TTS archive directory changed identity")
    hasher = hashlib.sha256()
    with open_binary_read_without_links(
        archive,
        expected_identity=metadata,
        expected_parent_identity=parent_identity,
    ) as handle:
        before = os.fstat(handle.fileno())
        if before.st_size != manifest.size:
            return (
                f"size mismatch: expected {manifest.size}, "
                f"got {before.st_size}"
            )
        while True:
            if is_interrupted is not None and is_interrupted():
                raise _DownloadInterrupted()
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
        after = os.fstat(handle.fileno())
    if not file_snapshot_is_stable(before, after):
        raise PermissionError(f"TTS archive changed while it was verified: {archive}")
    require_directory_identity(
        parent,
        parent_identity,
        field="TTS archive directory",
    )
    actual_sha256 = hasher.hexdigest()
    if actual_sha256.lower() != manifest.sha256.lower():
        return (
            "sha256 mismatch: expected "
            f"{manifest.sha256}, got {actual_sha256}"
        )
    return None


def _download_archive(
    url: str,
    archive: Path,
    headers: dict[str, str],
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    is_interrupted: Any | None = None,
    on_progress: Any | None = None,
    timeout: tuple[float, float] = (15, 600),
) -> None:
    download_url = _validated_download_url(url)
    archive.parent.mkdir(parents=True, exist_ok=True)
    parent, parent_identity = capture_directory_identity(
        archive.parent,
        field="TTS download directory",
    )
    if archive.parent != parent:
        raise PermissionError("TTS download directory changed identity")
    hasher = hashlib.sha256() if expected_sha256 is not None else None
    received = 0

    try:
        with requests.get(
            download_url,
            stream=True,
            timeout=timeout,
            headers=headers,
        ) as response:
            response.raise_for_status()
            final_url = str(getattr(response, "url", "") or "")
            if final_url:
                _validated_download_url(final_url)
            raw_total = str(response.headers.get("Content-Length", "0") or "0")
            try:
                total = int(raw_total)
            except ValueError:
                total = 0
            if total <= 0 and expected_size is not None:
                total = expected_size

            with atomic_binary_writer(
                archive,
                expected_parent_identity=parent_identity,
            ) as handle:
                for chunk in response.iter_content(_DOWNLOAD_CHUNK_SIZE):
                    if is_interrupted is not None and is_interrupted():
                        raise _DownloadInterrupted()
                    if not chunk:
                        continue
                    received += len(chunk)
                    if expected_size is not None and received > expected_size:
                        raise ValueError(
                            "verification failed: size exceeds expected "
                            f"{expected_size} bytes"
                        )
                    handle.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    if on_progress is None:
                        continue
                    if total > 0:
                        on_progress(min(70, int(70 * received / total)))
                    else:
                        on_progress(
                            min(35, received // (10 * 1024 * 1024))
                        )
                if expected_size is not None and received != expected_size:
                    raise ValueError(
                        "verification failed: size mismatch: "
                        f"expected {expected_size}, got {received}"
                    )
                if hasher is not None:
                    actual_sha256 = hasher.hexdigest()
                    if actual_sha256.lower() != str(expected_sha256).lower():
                        raise ValueError(
                            "verification failed: sha256 mismatch: expected "
                            f"{expected_sha256}, got {actual_sha256}"
                        )
    except requests.exceptions.ReadTimeout:
        if is_interrupted is not None and is_interrupted():
            raise _DownloadInterrupted() from None
        raise

    require_directory_identity(
        parent,
        parent_identity,
        field="TTS download directory",
    )


def _load_py7zz() -> Any | None:
    try:
        return importlib.import_module("py7zz")
    except ImportError:  # pragma: no cover - optional dependency
        return None


def _load_py7zr() -> Any | None:
    try:
        return importlib.import_module("py7zr")
    except ImportError:  # pragma: no cover - optional dependency
        return None


def _direct_seven_zip_candidates() -> list[Path]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            for name in _SEVEN_ZIP_COMMANDS:
                candidates.append(Path(meipass) / "7za" / name)
    roots: list[Path] = []
    for root_factory in (app_root, source_root):
        try:
            root = root_factory()
        except (OSError, RuntimeError, ValueError):
            continue
        if root not in roots:
            roots.append(root)
    for root in roots:
        for name in _SEVEN_ZIP_COMMANDS:
            candidates.append(root / "build_exe" / name)
    return candidates


def _seven_zip_executable() -> LaunchFileSnapshot | None:
    for candidate in _direct_seven_zip_candidates():
        try:
            return capture_launch_file(
                candidate,
                field="7-Zip executable",
                executable=True,
            )
        except (OSError, PermissionError, RuntimeError, ValueError):
            continue
    for name in _SEVEN_ZIP_COMMANDS:
        try:
            return capture_command_executable(
                name,
                field="7-Zip executable",
            )
        except (OSError, PermissionError, RuntimeError, ValueError):
            continue
    return None


def _extract_7za(
    executable: LaunchFileSnapshot,
    archive: LaunchFileSnapshot,
    output: LaunchDirectorySnapshot,
    *,
    is_interrupted: Any | None = None,
) -> str | None:
    output_text = str(output.path)
    if not output_text.endswith(("/", "\\")):
        output_text += "\\" if sys.platform == "win32" else "/"
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _WIN_NO_WINDOW
    try:
        process = popen_with_stable_paths(
            [
                executable.path,
                "x",
                "-y",
                f"-o{output_text}",
                archive.path,
            ],
            cwd=output,
            executable=executable,
            required_files=(archive,),
            **kwargs,
        )
    except OSError as exc:  # pragma: no cover - host executable failure
        return str(exc)[:2000]

    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if is_interrupted is None or not is_interrupted():
                continue
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise _ExtractionInterrupted()
    require_launch_snapshots(directories=(output,), files=(archive, executable))
    if process.returncode != 0:
        error = (stderr or stdout or "").strip() or f"exit {process.returncode}"
        return error[:2000]
    return None


def _validate_extracted_tree(
    output: LaunchDirectorySnapshot,
    archive: LaunchFileSnapshot,
) -> None:
    require_launch_snapshots(directories=(output,), files=(archive,))
    inspect_portable_directory_tree(output.path)
    require_launch_snapshots(directories=(output,), files=(archive,))


def _clear_extraction_output(output: LaunchDirectorySnapshot) -> None:
    clear_directory_without_links(
        output.path,
        expected_identity=output.identity,
    )


def _extract_py7zz(
    archive: LaunchFileSnapshot,
    output: LaunchDirectorySnapshot,
) -> str | None:
    py7zz = _load_py7zz()
    if py7zz is None:
        return "missing"
    require_launch_snapshots(directories=(output,), files=(archive,))
    try:
        py7zz.extract_archive(str(archive.path), str(output.path))
    except Exception as exc:
        return str(exc)[:2000]
    _validate_extracted_tree(output, archive)
    return None


def _py7zr_targets(archive_reader: Any) -> list[str]:
    try:
        names = archive_reader.getnames()
    except Exception as exc:
        raise ValueError("py7zr could not enumerate archive members") from exc
    if not isinstance(names, list):
        names = list(names or ())
    normalized = [str(name) for name in names if str(name)]
    validate_archive_member_names(normalized)
    return [name for name in normalized if not name.endswith(("/", "\\"))]


def _extract_py7zr(
    py7zr: Any,
    archive: LaunchFileSnapshot,
    output: LaunchDirectorySnapshot,
    *,
    is_interrupted: Any | None = None,
    on_progress: Any | None = None,
) -> None:
    require_launch_snapshots(directories=(output,), files=(archive,))
    with py7zr.SevenZipFile(archive.path, "r") as reader:
        targets = _py7zr_targets(reader)
        if not targets:
            raise ValueError("TTS archive contains no extractable files")
        for index, name in enumerate(targets):
            if is_interrupted is not None and is_interrupted():
                raise _ExtractionInterrupted()
            reader.extract(path=output.path, targets=[name])
            if on_progress is not None:
                on_progress(70 + int(30 * (index + 1) / len(targets)))
    _validate_extracted_tree(output, archive)


def _extract_archive(
    archive: Path,
    out_dir: Path,
    *,
    is_interrupted: Any | None = None,
    on_progress: Any | None = None,
) -> str | None:
    archive_snapshot = capture_launch_file(
        archive,
        field="TTS archive",
    )
    output_snapshot = capture_launch_directory(
        out_dir,
        field="TTS extraction directory",
    )
    seven_zip = _seven_zip_executable()

    if is_interrupted is not None and seven_zip is not None:
        cli_error = _extract_7za(
            seven_zip,
            archive_snapshot,
            output_snapshot,
            is_interrupted=is_interrupted,
        )
        if cli_error is None:
            _validate_extracted_tree(output_snapshot, archive_snapshot)
            if on_progress is not None:
                on_progress(100)
            return None
        _clear_extraction_output(output_snapshot)

    py7zz_error = _extract_py7zz(archive_snapshot, output_snapshot)
    if py7zz_error is None:
        if on_progress is not None:
            on_progress(100)
        return None

    if seven_zip is not None:
        if py7zz_error != "missing":
            _clear_extraction_output(output_snapshot)
        cli_error = _extract_7za(
            seven_zip,
            archive_snapshot,
            output_snapshot,
            is_interrupted=is_interrupted,
        )
        if cli_error is None:
            _validate_extracted_tree(output_snapshot, archive_snapshot)
            if on_progress is not None:
                on_progress(100)
            return None
        if py7zz_error != "missing":
            return f"py7zz: {py7zz_error}\n7-Zip: {cli_error}"[:2000]
        return cli_error

    py7zr = _load_py7zr()
    if py7zr is None:
        return "7za"
    if py7zz_error != "missing":
        _clear_extraction_output(output_snapshot)
    try:
        _extract_py7zr(
            py7zr,
            archive_snapshot,
            output_snapshot,
            is_interrupted=is_interrupted,
            on_progress=on_progress,
        )
    except _ExtractionInterrupted:
        raise
    except Exception as exc:
        return (
            "external 7-Zip CLI is required for this archive; "
            f"py7zr fallback failed: {exc}"
        )[:2000]
    return None


def _resolve_extracted_root(
    extract_to: Path,
    *,
    expected_root_identity: os.stat_result | None = None,
) -> Path:
    root = require_directory_without_links(
        extract_to,
        field="TTS extraction root",
    )
    if expected_root_identity is not None:
        require_directory_identity(
            root,
            expected_root_identity,
            field="TTS extraction root",
        )
    inspect_portable_directory_tree(root)
    root, root_identity, entries = snapshot_directory_entries_without_links(
        root,
        field="TTS extraction root",
    )
    if (
        expected_root_identity is not None
        and not os.path.samestat(expected_root_identity, root_identity)
    ):
        raise PermissionError(f"TTS extraction root identity changed: {root}")

    visible_directories: list[tuple[Path, os.stat_result]] = []
    for entry, metadata in entries:
        if entry.name.startswith("."):
            continue
        if stat.S_ISDIR(metadata.st_mode):
            visible_directories.append((entry, metadata))
    if len(visible_directories) != 1:
        return root

    candidate, expected_identity = visible_directories[0]
    selected = require_directory_without_links(
        candidate,
        field="extracted TTS bundle root",
    )
    if not os.path.samestat(expected_identity, selected.lstat()):
        raise PermissionError(
            f"extracted TTS bundle root identity changed: {selected}"
        )
    require_directory_identity(
        root,
        root_identity,
        field="TTS extraction root",
    )
    return selected


def _publish_extracted_bundle(
    staging: Path,
    destination: Path,
    *,
    expected_staging_identity: os.stat_result,
    expected_destination_identity: os.stat_result | None,
) -> Path:
    parent, parent_identity = capture_directory_identity(
        destination.parent,
        field="TTS installation directory",
    )
    if staging.parent != parent or destination.parent != parent:
        raise PermissionError("TTS publication paths changed parent")
    inspect_portable_directory_tree(staging)
    return replace_directory_transactionally(
        staging,
        destination,
        expected_staging_identity=expected_staging_identity,
        expected_destination_identity=expected_destination_identity,
        expected_parent_identity=parent_identity,
    )


def _rmtree(
    path: Path,
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if (
        _metadata_is_link_or_reparse_point(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise NotADirectoryError(path)
    if expected_identity is not None and not os.path.samestat(
        expected_identity,
        metadata,
    ):
        raise PermissionError(f"directory removal target identity changed: {path}")
    remove_directory_without_links(
        path,
        expected_identity=metadata,
    )


__all__ = [
    "_BUNDLE_IO_LOCK",
    "_DownloadInterrupted",
    "_ExtractionInterrupted",
    "_archive_filename",
    "_archive_verification_error",
    "_bundle_storage_paths",
    "_download_archive",
    "_extract_archive",
    "_publish_extracted_bundle",
    "_resolve_extracted_root",
    "_rmtree",
]
