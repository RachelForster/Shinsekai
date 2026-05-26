"""后台下载并解压 TTS 整合包，向 UI 报告进度。"""

from __future__ import annotations

import hashlib
import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QObject, QThread, Signal

from ui.settings_ui.tts.tts_bundle_manifest import (
    TtsBundleManifestEntry,
    bundle_manifest_for_key,
)
from ui.settings_ui.tts.tts_env_probe import get_default_project_root

_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_DOWNLOAD_CHUNK_SIZE = 512 * 1024
_HASH_CHUNK_SIZE = 4 * 1024 * 1024
_SEVEN_ZIP_COMMANDS = (
    "7zz.exe",
    "7za.exe",
    "7z.exe",
    "7zz",
    "7za",
    "7z",
)


class _DownloadInterrupted(Exception):
    pass


class _ExtractionInterrupted(Exception):
    pass


def _load_py7zz() -> Any | None:
    """py7zz bundles the cross-platform 7zz CLI as a pip dependency."""
    try:
        return importlib.import_module("py7zz")
    except ImportError:  # pragma: no cover
        return None


def _load_py7zr() -> Any | None:
    """Pure Python fallback; it cannot extract BCJ2 archives."""
    try:
        return importlib.import_module("py7zr")
    except ImportError:  # pragma: no cover
        return None


def _seven_zip_exe() -> Path | None:
    """Find an external 7-Zip CLI shipped with the app or available on PATH."""
    if getattr(sys, "frozen", False):
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            for name in _SEVEN_ZIP_COMMANDS:
                p = Path(meip) / "7za" / name
                if p.is_file():
                    return p
    project_root = get_default_project_root()
    for name in _SEVEN_ZIP_COMMANDS:
        p = project_root / "build_exe" / name
        if p.is_file():
            return p
    for name in _SEVEN_ZIP_COMMANDS:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _extract_7za(exe: Path, archive: Path, out_dir: Path) -> str | None:
    """用 7-Zip 独立程序解压。成功返回 None，失败返回短错误信息。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    # -o 后路径末尾：7z 对目录参数要求
    odir = str(out_dir.resolve())
    if not odir.endswith(("/", "\\")):
        odir = odir + ("\\" if sys.platform == "win32" else "/")
    cmd = [str(exe), "x", "-y", f"-o{odir}", str(archive)]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            creationflags=_WIN_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError as e:  # pragma: no cover
        return str(e)[:2000]
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        return err[:2000]
    return None


def _extract_py7zz(archive: Path, out_dir: Path) -> str | None:
    p7zz = _load_py7zz()
    if p7zz is None:
        return "missing"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        p7zz.extract_archive(str(archive), str(out_dir))
    except Exception as e:
        return str(e)[:2000]
    return None


def _extract_py7zr(
    p7: Any,
    archive: Path,
    out_dir: Path,
    *,
    is_interrupted: Any | None = None,
    on_progress: Any | None = None,
) -> None:
    with p7.SevenZipFile(archive, "r") as z:
        targets = _list_targets(z)
        n = len(targets)
        if n == 0 or n > 1000:
            z.extractall(path=out_dir)
            if on_progress is not None:
                on_progress(100)
            return
        for i, name in enumerate(targets):
            if is_interrupted is not None and is_interrupted():
                raise _ExtractionInterrupted()
            z.extract(path=out_dir, targets=[name])
            if on_progress is not None:
                on_progress(70 + int(30 * (i + 1) / n))


def _extract_archive(
    archive: Path,
    out_dir: Path,
    *,
    is_interrupted: Any | None = None,
    on_progress: Any | None = None,
) -> str | None:
    """Extract with external 7-Zip first; py7zr is only a last fallback."""
    py7zz_err = _extract_py7zz(archive, out_dir)
    if py7zz_err is None:
        return None

    sz = _seven_zip_exe()
    if sz is not None:
        if py7zz_err != "missing":
            _rmtree(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
        cli_err = _extract_7za(sz, archive, out_dir)
        if cli_err is None:
            return None
        if py7zz_err != "missing":
            return f"py7zz: {py7zz_err}\n7-Zip: {cli_err}"[:2000]
        return cli_err

    p7 = _load_py7zr()
    if p7 is None:
        return "7za"
    try:
        _extract_py7zr(
            p7,
            archive,
            out_dir,
            is_interrupted=is_interrupted,
            on_progress=on_progress,
        )
    except _ExtractionInterrupted:
        raise
    except Exception as e:
        return (
            "external 7-Zip CLI is required for this archive; "
            f"py7zr fallback failed: {e}"
        )[:2000]
    return None


def _archive_filename(url: str) -> str:
    path = unquote(urlparse(url).path)
    return path.rsplit("/", 1)[-1] or "bundle.7z"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _archive_verification_error(
    archive: Path, manifest: TtsBundleManifestEntry
) -> str | None:
    if not archive.is_file():
        return "archive is missing"
    try:
        actual_size = archive.stat().st_size
    except OSError as e:
        return str(e)
    if actual_size != manifest.size:
        return f"size mismatch: expected {manifest.size}, got {actual_size}"
    try:
        actual_sha256 = _sha256_file(archive)
    except OSError as e:
        return str(e)
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
) -> None:
    part = archive.with_name(f"{archive.name}.part")
    if part.exists():
        part.unlink()
    try:
        hasher = hashlib.sha256() if expected_sha256 is not None else None
        with requests.get(url, stream=True, timeout=(15, 600), headers=headers) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0") or 0)
            if total <= 0 and expected_size is not None:
                total = expected_size
            n = 0
            with part.open("wb") as f:
                for chunk in r.iter_content(_DOWNLOAD_CHUNK_SIZE):
                    if is_interrupted is not None and is_interrupted():
                        raise _DownloadInterrupted()
                    if not chunk:
                        continue
                    f.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    n += len(chunk)
                    if on_progress is None:
                        continue
                    if total > 0:
                        on_progress(min(70, int(70 * n / total)))
                    else:
                        on_progress(min(35, n // (10 * 1024 * 1024)))
        if expected_size is not None and n != expected_size:
            raise ValueError(
                f"verification failed: size mismatch: expected {expected_size}, got {n}"
            )
        if hasher is not None:
            actual_sha256 = hasher.hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                raise ValueError(
                    "verification failed: sha256 mismatch: expected "
                    f"{expected_sha256}, got {actual_sha256}"
                )
        archive.parent.mkdir(parents=True, exist_ok=True)
        part.replace(archive)
    except Exception:
        if part.exists():
            part.unlink()
        raise


def _rmtree(p: Path) -> None:
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)


def _resolve_extracted_root(extract_to: Path) -> Path:
    if not extract_to.is_dir():
        return extract_to.resolve()
    sub = [x for x in extract_to.iterdir() if not x.name.startswith(".")]
    if len(sub) == 1 and sub[0].is_dir():
        return sub[0].resolve()
    return extract_to.resolve()


def _list_targets(z: Any) -> list[str]:
    try:
        names = z.getnames()
    except Exception:  # pragma: no cover
        return []
    if not names:
        return []
    return [n for n in names if n and not n.endswith("/")]


class TtsBundleDownloadWorker(QThread):
    """在子线程中下载到 data/tts_bundles，解压并返回 TTS 根目录绝对路径。"""

    progress = Signal(int)  # 0-100
    status = Signal(str)
    finished_ok = Signal(str)  # 绝对路径
    failed = Signal(str)

    def __init__(
        self,
        download_url: str,
        bundle_dir_key: str,
        project_root: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = download_url
        self._key = bundle_dir_key
        self._root = (project_root or get_default_project_root()).resolve()

    def run(self) -> None:  # pragma: no cover - UI thread
        base = self._root / "data" / "tts_bundles"
        dl_dir = base / "downloads"
        out_dir = base / "installed" / self._key
        dl_dir.mkdir(parents=True, exist_ok=True)
        manifest = bundle_manifest_for_key(self._key)
        local_name = (
            manifest.filename if manifest is not None else _archive_filename(self._url)
        )
        archive = dl_dir / local_name

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
        }

        archive_ready = False
        if manifest is not None and archive.exists():
            self.status.emit("verify")
            self.progress.emit(1)
            archive_ready = _archive_verification_error(archive, manifest) is None

        if not archive_ready:
            self.status.emit("download")
            try:
                _download_archive(
                    self._url,
                    archive,
                    headers,
                    expected_size=manifest.size if manifest is not None else None,
                    expected_sha256=manifest.sha256 if manifest is not None else None,
                    is_interrupted=self.isInterruptionRequested,
                    on_progress=self.progress.emit,
                )
            except _DownloadInterrupted:
                return
            except Exception as e:
                self.failed.emit(f"download: {e}")
                return

        self.progress.emit(70)
        self.status.emit("extract")

        _archive_str = str(archive.resolve())
        _rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            err = _extract_archive(
                archive,
                out_dir,
                is_interrupted=self.isInterruptionRequested,
                on_progress=self.progress.emit,
            )
        except _ExtractionInterrupted:
            return
        if err is not None:
            if err == "7za":
                self.failed.emit(f"7za||{_archive_str}")
            else:
                self.failed.emit(f"extract: {err}||{_archive_str}")
            return

        self.progress.emit(100)
        root = _resolve_extracted_root(out_dir)
        self.finished_ok.emit(str(root.resolve()))
