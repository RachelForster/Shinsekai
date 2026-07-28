"""Deprecated Qt worker backed by the host-owned TTS archive service."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from core.model_assets.tts_bundle_archive import (
    _DownloadInterrupted,
    _ExtractionInterrupted,
    _archive_filename,
    _archive_verification_error,
    _download_archive,
    _extract_archive,
    _resolve_extracted_root,
    _rmtree,
)
from core.model_assets.tts_bundle_manifest import bundle_manifest_for_key
from core.model_assets.tts_environment import get_default_project_root
from frontend_bridge_core.path_utils import strip_windows_verbatim_prefix


class TtsBundleDownloadWorker(QThread):
    """在子线程中下载到 data/tts_bundles，解压并返回 TTS 根目录绝对路径。"""

    progress = Signal(int)
    status = Signal(str)
    finished_ok = Signal(str)
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

    def run(self) -> None:  # pragma: no cover - deprecated Qt thread
        base = self._root / "data" / "tts_bundles"
        dl_dir = base / "downloads"
        out_dir = base / "installed" / self._key
        dl_dir.mkdir(parents=True, exist_ok=True)
        manifest = bundle_manifest_for_key(self._key)
        local_name = (
            manifest.filename
            if manifest is not None
            else _archive_filename(self._url)
        )
        archive = dl_dir / local_name
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) EasyAI-Desktop/1.0"
            )
        }

        archive_ready = False
        if manifest is not None and archive.exists():
            self.status.emit("verify")
            self.progress.emit(1)
            archive_ready = (
                _archive_verification_error(archive, manifest) is None
            )

        if not archive_ready:
            self.status.emit("download")
            try:
                _download_archive(
                    self._url,
                    archive,
                    headers,
                    expected_size=(
                        manifest.size if manifest is not None else None
                    ),
                    expected_sha256=(
                        manifest.sha256 if manifest is not None else None
                    ),
                    is_interrupted=self.isInterruptionRequested,
                    on_progress=self.progress.emit,
                )
            except _DownloadInterrupted:
                return
            except Exception as exc:
                self.failed.emit(f"download: {exc}")
                return

        self.progress.emit(70)
        self.status.emit("extract")
        archive_text = str(archive.resolve())
        _rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            error = _extract_archive(
                archive,
                out_dir,
                is_interrupted=self.isInterruptionRequested,
                on_progress=self.progress.emit,
            )
        except _ExtractionInterrupted:
            return
        if error is not None:
            prefix = "7za" if error == "7za" else f"extract: {error}"
            self.failed.emit(f"{prefix}||{archive_text}")
            return

        self.progress.emit(100)
        root = _resolve_extracted_root(out_dir)
        self.finished_ok.emit(
            strip_windows_verbatim_prefix(str(root.resolve()))
        )
