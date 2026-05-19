"""后台下载并解压 TTS 整合包，向 UI 报告进度。"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QObject, QThread, Signal

from ui.settings_ui.tts.tts_env_probe import get_default_project_root

_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_MAX_7Z_MEMBERS = 100_000
_MAX_7Z_MEMBER_SIZE = 16 * 1024 * 1024 * 1024
_MAX_7Z_TOTAL_SIZE = 80 * 1024 * 1024 * 1024
_MAX_7Z_COMPRESSION_RATIO = 1000.0


def _load_py7zr() -> Any | None:
    """开发环境用纯 Python 的 py7zr；生产 exe 用打包的 7za.exe。"""
    try:
        return importlib.import_module("py7zr")
    except ImportError:  # pragma: no cover
        return None


def _seven_zip_exe() -> Path | None:
    """生产：PyInstaller 将 build_exe/7za.exe 打进 _internal/7za/7za.exe。开发：仓库 build_exe/7za.exe。"""
    if getattr(sys, "frozen", False):
        meip = getattr(sys, "_MEIPASS", None)
        if not meip:
            return None
        p = Path(meip) / "7za" / "7za.exe"
        return p if p.is_file() else None
    p = get_default_project_root() / "build_exe" / "7za.exe"
    return p if p.is_file() else None


def _extract_7za(exe: Path, archive: Path, out_dir: Path) -> str | None:
    """用 7-Zip 独立程序解压。成功返回 None，失败返回短错误信息。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries, err = _list_7za_entries(exe, archive)
    if err is not None:
        return err
    try:
        _validate_7za_entries(entries)
    except ValueError as e:
        return str(e)[:2000]

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


def _archive_filename(url: str) -> str:
    path = unquote(urlparse(url).path)
    return path.rsplit("/", 1)[-1] or "bundle.7z"


def _safe_bundle_dir_key(raw: str) -> str:
    key = str(raw or "").strip()
    posix = PurePosixPath(key.replace("\\", "/"))
    windows = PureWindowsPath(key)
    if (
        not key
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or len(posix.parts) != 1
        or any(part in ("", ".", "..") for part in posix.parts)
    ):
        raise ValueError(f"unsafe bundle_dir_key: {raw!r}")
    return key


def _safe_archive_member_path(raw_name: str) -> Path:
    raw = str(raw_name or "").strip().replace("\\", "/")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(str(raw_name or ""))
    if (
        not raw
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in ("", ".", "..") for part in posix.parts)
    ):
        raise ValueError(f"unsafe 7z member path: {raw_name!r}")
    return Path(*posix.parts)


def _validate_archive_member_names(names: Iterable[str]) -> list[str]:
    safe_names: list[str] = []
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        _safe_archive_member_path(text)
        safe_names.append(text)
        if len(safe_names) > _MAX_7Z_MEMBERS:
            raise ValueError("7z archive has too many members")
    if not safe_names:
        raise ValueError("7z archive is empty")
    return safe_names


def _list_names(z: Any) -> list[str]:
    try:
        names = z.getnames()
    except Exception:  # pragma: no cover
        return []
    return [str(n) for n in names or []]


def _validate_py7zr_archive(z: Any) -> list[str]:
    try:
        infos = list(z.list())
    except Exception:  # pragma: no cover
        return [n for n in _validate_archive_member_names(_list_names(z)) if not n.endswith("/")]

    targets: list[str] = []
    total = 0
    for info in infos:
        name = str(getattr(info, "filename", "") or "")
        _safe_archive_member_path(name)
        is_dir = bool(getattr(info, "is_directory", False))
        is_file = bool(getattr(info, "is_file", False))
        is_symlink = bool(getattr(info, "is_symlink", False))
        if is_symlink or not (is_dir or is_file):
            raise ValueError(f"unsupported 7z member type: {name!r}")
        if is_dir:
            continue
        uncompressed = int(getattr(info, "uncompressed", 0) or 0)
        compressed = int(getattr(info, "compressed", 0) or 0)
        if uncompressed > _MAX_7Z_MEMBER_SIZE:
            raise ValueError(f"7z member too large: {name!r}")
        total += uncompressed
        if total > _MAX_7Z_TOTAL_SIZE:
            raise ValueError("7z archive uncompressed size is too large")
        if compressed == 0 and uncompressed > 0:
            raise ValueError(f"7z member has invalid packed size: {name!r}")
        if compressed > 0 and uncompressed / compressed > _MAX_7Z_COMPRESSION_RATIO:
            raise ValueError(f"7z member compression ratio is too high: {name!r}")
        targets.append(name)
        if len(targets) > _MAX_7Z_MEMBERS:
            raise ValueError("7z archive has too many members")
    if not targets:
        raise ValueError("7z archive is empty")
    return targets


def _parse_7za_slt_paths(stdout: str) -> list[str]:
    return [
        str(entry.get("Path", "")).strip()
        for entry in _parse_7za_slt_entries(stdout)
        if str(entry.get("Path", "")).strip()
    ]


def _parse_7za_slt_entries(stdout: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    in_files = False
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if line.startswith("----------"):
            if cur:
                entries.append(cur)
                cur = {}
            in_files = True
            continue
        if in_files and " = " in line:
            key, value = line.split(" = ", 1)
            cur[key.strip()] = value.strip()
    if cur:
        entries.append(cur)
    return entries


def _parse_7za_int(value: object) -> int:
    try:
        return int(str(value or "0").strip() or "0")
    except ValueError:
        return 0


def _validate_7za_entries(entries: Iterable[dict[str, str]]) -> list[str]:
    targets: list[str] = []
    total = 0
    for entry in entries:
        name = str(entry.get("Path", "") or "").strip()
        if not name:
            continue
        _safe_archive_member_path(name)
        attrs = str(entry.get("Attributes", "") or "")
        is_dir = attrs.startswith("D") or name.endswith("/")
        if is_dir:
            continue
        uncompressed = _parse_7za_int(entry.get("Size", "0"))
        compressed = _parse_7za_int(entry.get("Packed Size", "0"))
        if uncompressed > _MAX_7Z_MEMBER_SIZE:
            raise ValueError(f"7z member too large: {name!r}")
        total += uncompressed
        if total > _MAX_7Z_TOTAL_SIZE:
            raise ValueError("7z archive uncompressed size is too large")
        if compressed == 0 and uncompressed > 0:
            raise ValueError(f"7z member has invalid packed size: {name!r}")
        if compressed > 0 and uncompressed / compressed > _MAX_7Z_COMPRESSION_RATIO:
            raise ValueError(f"7z member compression ratio is too high: {name!r}")
        targets.append(name)
        if len(targets) > _MAX_7Z_MEMBERS:
            raise ValueError("7z archive has too many members")
    if not targets:
        raise ValueError("7z archive is empty")
    return targets


def _list_7za_entries(exe: Path, archive: Path) -> tuple[list[dict[str, str]], str | None]:
    cmd = [str(exe), "l", "-slt", str(archive)]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            creationflags=_WIN_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError as e:  # pragma: no cover
        return [], str(e)[:2000]
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
        return [], err[:2000]
    return _parse_7za_slt_entries(r.stdout or ""), None


def _list_7za_paths(exe: Path, archive: Path) -> tuple[list[str], str | None]:
    entries, err = _list_7za_entries(exe, archive)
    if err is not None:
        return [], err
    return [str(e.get("Path", "") or "").strip() for e in entries], None


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


def _replace_installed_tree(staging_dir: Path, final_dir: Path) -> None:
    backup_dir = final_dir.with_name(f".{final_dir.name}.previous")
    _rmtree(backup_dir)
    had_previous = final_dir.exists()
    if had_previous:
        shutil.move(str(final_dir), str(backup_dir))
    try:
        shutil.move(str(staging_dir), str(final_dir))
    except Exception:
        if had_previous and backup_dir.exists() and not final_dir.exists():
            shutil.move(str(backup_dir), str(final_dir))
        raise
    _rmtree(backup_dir)


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
        self._key = _safe_bundle_dir_key(bundle_dir_key)
        self._root = (project_root or get_default_project_root()).resolve()

    def run(self) -> None:  # pragma: no cover - UI thread
        base = self._root / "data" / "tts_bundles"
        dl_dir = base / "downloads"
        final_dir = base / "installed" / self._key
        out_dir = base / "_extracting" / self._key
        dl_dir.mkdir(parents=True, exist_ok=True)
        local_name = _archive_filename(self._url)
        archive = dl_dir / local_name
        _rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
        }
        installed = False
        try:
            self.status.emit("download")
            try:
                with requests.get(
                    self._url, stream=True, timeout=(15, 600), headers=headers
                ) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", "0") or 0)
                    n = 0
                    with open(archive, "wb") as f:
                        for chunk in r.iter_content(512 * 1024):
                            if self.isInterruptionRequested():
                                return
                            if not chunk:
                                continue
                            f.write(chunk)
                            n += len(chunk)
                            if total > 0:
                                pct = min(70, int(70 * n / total))
                                self.progress.emit(pct)
                            else:
                                self.progress.emit(min(35, n // (10 * 1024 * 1024)))
            except Exception as e:
                self.failed.emit(f"download: {e}")
                return

            self.progress.emit(70)
            self.status.emit("extract")

            _archive_str = str(archive.resolve())
            sz = _seven_zip_exe()
            if getattr(sys, "frozen", False):
                if sz is None:
                    self.failed.emit(f"7za||{_archive_str}")
                    return
                err = _extract_7za(sz, archive, out_dir)
                if err is not None:
                    self.failed.emit(f"extract: {err}||{_archive_str}")
                    return
            else:
                p7 = _load_py7zr()
                if p7 is not None:
                    try:
                        with p7.SevenZipFile(archive, "r") as z:
                            targets = _validate_py7zr_archive(z)
                            n = len(targets)
                            if n > 1000:
                                z.extractall(path=out_dir)
                                self.progress.emit(100)
                            else:
                                for i, name in enumerate(targets):
                                    if self.isInterruptionRequested():
                                        return
                                    z.extract(path=out_dir, targets=[name])
                                    self.progress.emit(70 + int(30 * (i + 1) / n))
                    except Exception as e:
                        self.failed.emit(f"extract: {e}||{_archive_str}")
                        return
                elif sz is not None:
                    err = _extract_7za(sz, archive, out_dir)
                    if err is not None:
                        self.failed.emit(f"extract: {err}||{_archive_str}")
                        return
                else:
                    self.failed.emit(f"py7zr||{_archive_str}")
                    return

            final_dir.parent.mkdir(parents=True, exist_ok=True)
            _replace_installed_tree(out_dir, final_dir)
            installed = True
            self.progress.emit(100)
            root = _resolve_extracted_root(final_dir)
            self.finished_ok.emit(str(root.resolve()))
        finally:
            if not installed:
                _rmtree(out_dir)
