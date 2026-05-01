"""后台下载并解压 TTS 整合包，向 UI 报告进度。"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QObject, QThread, Signal

from ui.settings_ui.tts_env_probe import get_default_project_root

_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


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
        local_name = _archive_filename(self._url)
        archive = dl_dir / local_name
        _rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
        }
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

        sz = _seven_zip_exe()
        if getattr(sys, "frozen", False):
            if sz is None:
                self.failed.emit("7za")
                return
            err = _extract_7za(sz, archive, out_dir)
            if err is not None:
                self.failed.emit(f"extract: {err}")
                return
        else:
            p7 = _load_py7zr()
            if p7 is not None:
                try:
                    with p7.SevenZipFile(archive, "r") as z:
                        targets = _list_targets(z)
                        n = len(targets)
                        if n == 0 or n > 1000:
                            z.extractall(path=out_dir)
                            self.progress.emit(100)
                        else:
                            for i, name in enumerate(targets):
                                if self.isInterruptionRequested():
                                    return
                                z.extract(path=out_dir, targets=[name])
                                self.progress.emit(70 + int(30 * (i + 1) / n))
                except Exception as e:
                    self.failed.emit(f"extract: {e}")
                    return
            elif sz is not None:
                err = _extract_7za(sz, archive, out_dir)
                if err is not None:
                    self.failed.emit(f"extract: {err}")
                    return
            else:
                self.failed.emit("py7zr")
                return

        self.progress.emit(100)
        root = _resolve_extracted_root(out_dir)
        self.finished_ok.emit(str(root.resolve()))
