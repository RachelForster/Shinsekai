from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

TaskUpdate = Callable[..., None]

HUGGINGFACE_DOWNLOAD_PROGRESS_START = 0.02
HUGGINGFACE_DOWNLOAD_PROGRESS_END = 0.85
HUGGINGFACE_LOAD_PROGRESS = 0.92
HUGGINGFACE_PROGRESS_LOG_LIMIT = 20
HUGGINGFACE_PROGRESS_UPDATE_INTERVAL_SEC = 0.25
_HUGGINGFACE_SYMLINK_PROBE_LOCK = threading.Lock()


def _disable_huggingface_terminal_progress_without_stderr() -> None:
    """Keep Hugging Face worker progress bars out of terminal-less processes."""
    if callable(getattr(sys.stderr, "write", None)):
        return
    try:
        from huggingface_hub.utils import disable_progress_bars
    except (ImportError, AttributeError):
        return

    # huggingface_hub 0.x applies snapshot_download's custom tqdm class only
    # to the outer file counter. Its worker threads still create regular tqdm
    # bars, and under pythonw those bars can deadlock on tqdm's shared lock
    # because sys.stderr is None. The desktop UI reports progress through
    # update_task, so terminal bars are both unsafe and redundant here.
    disable_progress_bars()


def _prime_windows_huggingface_symlink_support(
    repo_id: str,
    *,
    cache_dir: Any = None,
    repo_type: Any = None,
) -> None:
    """Finish Hugging Face's symlink probe before snapshot worker threads start."""
    if sys.platform != "win32":
        return
    try:
        from huggingface_hub.file_download import are_symlinks_supported, repo_folder_name
    except ImportError:
        return

    # huggingface_hub 0.x initializes its per-cache result optimistically.
    # Concurrent first-use downloads can observe that temporary True value
    # before the Windows privilege probe changes it to False, then fail with
    # WinError 1314. A single probe here makes the later worker reads stable.
    if cache_dir is None:
        from huggingface_hub.constants import HF_HUB_CACHE

        cache_dir = HF_HUB_CACHE
    storage_folder = Path(cache_dir) / repo_folder_name(
        repo_id=repo_id,
        repo_type=str(repo_type or "model"),
    )
    with _HUGGINGFACE_SYMLINK_PROBE_LOCK:
        are_symlinks_supported(storage_folder)


def preload_huggingface_snapshot(
    repo_id: str,
    *,
    cached: bool,
    update_task: TaskUpdate,
    download_message: str,
    cached_message: str,
    load_message: str,
    post_download_phase: str = "reload",
    **snapshot_kwargs: Any,
) -> str | None:
    """Download a HuggingFace repository snapshot and report task progress.

    HuggingFace snapshot downloads expose file-level progress through
    ``tqdm_class``. This helper maps that progress into the shared task shape
    used by the React ``TaskProgress`` component.
    """
    if cached:
        update_task(
            phase="reload",
            message=cached_message,
            progress=HUGGINGFACE_LOAD_PROGRESS,
        )
        return None

    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import tqdm as hf_tqdm

    progress_lock = threading.Lock()
    progress_logs: list[str] = []
    last_progress_update = 0.0
    last_progress_value: float | None = None
    byte_progress_seen = False

    def format_bytes(value: float) -> str:
        size = float(max(0.0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024

    def push_progress_log(line: str) -> list[str]:
        text = " ".join(str(line or "").split())
        if text and (not progress_logs or progress_logs[-1] != text):
            progress_logs.append(text)
            del progress_logs[:-HUGGINGFACE_PROGRESS_LOG_LIMIT]
        return list(progress_logs)

    def mark_byte_progress() -> None:
        nonlocal byte_progress_seen, last_progress_update, last_progress_value
        with progress_lock:
            if byte_progress_seen:
                return
            byte_progress_seen = True
            # A byte bar is more precise than the legacy file-count fallback.
            # Reset throttling if a newer Hugging Face version exposes it after
            # the outer file bar has already emitted an update.
            last_progress_update = 0.0
            last_progress_value = None

    def update_download_progress(
        current: float,
        total: float,
        *,
        source: str,
        force: bool = False,
    ) -> None:
        nonlocal last_progress_update, last_progress_value
        if total <= 0:
            return
        current = min(max(0.0, current), total)
        ratio = min(1.0, max(0.0, current / total))
        progress = HUGGINGFACE_DOWNLOAD_PROGRESS_START + ratio * (
            HUGGINGFACE_DOWNLOAD_PROGRESS_END - HUGGINGFACE_DOWNLOAD_PROGRESS_START
        )
        now = time.monotonic()
        with progress_lock:
            if source == "files" and byte_progress_seen:
                return
            should_update = (
                force
                or last_progress_value is None
                or progress >= HUGGINGFACE_DOWNLOAD_PROGRESS_END
                or progress - last_progress_value >= 0.005
                or now - last_progress_update >= HUGGINGFACE_PROGRESS_UPDATE_INTERVAL_SEC
            )
            if not should_update:
                return
            last_progress_value = progress
            last_progress_update = now
            if source == "bytes":
                detail = f"{format_bytes(current)} / {format_bytes(total)}"
            else:
                detail = f"{int(current)} / {int(total)} files"
            message = f"{download_message} ({detail})."
            update_task(
                phase="download",
                message=message,
                progress=round(progress, 4),
                logs=push_progress_log(message),
            )

    class HuggingFaceSnapshotProgress(hf_tqdm):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._shinsekai_desc = kwargs.get("desc")
            self._shinsekai_unit = kwargs.get("unit")
            self._shinsekai_name = kwargs.get("name")
            self._shinsekai_total = kwargs.get("total")
            self._shinsekai_counter_lock = threading.RLock()
            self._shinsekai_progress_source = self._detect_progress_source()
            source = self._progress_source()
            if source == "bytes":
                mark_byte_progress()
            output = kwargs.get("file")
            if output is None:
                output = sys.stderr
            if source is not None and not callable(getattr(output, "write", None)):
                # pythonw has no stderr stream. Keep tqdm disabled and use our
                # own counters instead of letting its constructor write to None.
                kwargs["disable"] = True
            super().__init__(*args, **kwargs)
            # tqdm normalizes positional/default metadata during construction.
            # Confirm the source once more, then keep it stable for the hot
            # refresh/update/iteration paths.
            self._shinsekai_progress_source = self._detect_progress_source()
            if self._shinsekai_progress_source == "bytes":
                mark_byte_progress()
            self._report_progress(force=True)

        def _detect_progress_source(self) -> str | None:
            unit = str(self._shinsekai_unit or getattr(self, "unit", "") or "").lower()
            name = str(self._shinsekai_name or "").lower()
            desc = str(self._shinsekai_desc or getattr(self, "desc", "") or "").lower()
            total = self._shinsekai_total or getattr(self, "total", None)
            if (
                unit in {"b", "ib", "byte", "bytes"}
                or name == "huggingface_hub.snapshot_download"
                or (desc.startswith("download") and isinstance(total, (int, float)))
            ):
                return "bytes"
            # huggingface_hub < 1.0 only applies snapshot_download's custom
            # tqdm class to the outer "Fetching N files" bar. Individual byte
            # bars still render in the terminal but are not observable here.
            if desc.startswith("fetching ") and "file" in desc and isinstance(total, (int, float)):
                return "files"
            return None

        def _progress_source(self) -> str | None:
            return self._shinsekai_progress_source

        def _report_progress(self, *, force: bool = False) -> None:
            source = self._progress_source()
            if source is None:
                return
            update_download_progress(
                float(getattr(self, "n", 0) or 0),
                float(getattr(self, "total", 0) or 0),
                source=source,
                force=force,
            )

        def refresh(self, *args: Any, **kwargs: Any) -> bool | None:
            with self._shinsekai_counter_lock:
                result = super().refresh(*args, **kwargs)
                self._report_progress(force=True)
                return result

        def __iter__(self):
            if self._progress_source() != "files":
                yield from super().__iter__()
                return

            # tqdm's optimized iterator never calls update() when disabled and
            # can defer it until close() for short downloads. Drive the small
            # legacy snapshot file bar explicitly so every completed file is
            # observable in desktop/non-TTY mode as well.
            try:
                for item in self.iterable:
                    yield item
                    self.update(1)
            finally:
                self.close()

        def update(self, n: float = 1) -> bool | None:
            source = self._progress_source()
            if source is None:
                return super().update(n)
            with self._shinsekai_counter_lock:
                previous = float(getattr(self, "n", 0) or 0)
                result = super().update(n)
                current = float(getattr(self, "n", 0) or 0)
                if n and current <= previous:
                    # Disabled tqdm instances intentionally skip their own
                    # counter. Keep an internal count so desktop/pythonw mode
                    # still reports progress without forcing a partially
                    # initialized bar on.
                    current = previous + float(n)
                    self.n = current
                update_download_progress(
                    current,
                    float(getattr(self, "total", 0) or 0),
                    source=source,
                )
                return result

    update_task(
        phase="download",
        message=download_message,
        progress=HUGGINGFACE_DOWNLOAD_PROGRESS_START,
        logs=push_progress_log(download_message),
    )
    _disable_huggingface_terminal_progress_without_stderr()
    _prime_windows_huggingface_symlink_support(
        repo_id,
        cache_dir=snapshot_kwargs.get("cache_dir"),
        repo_type=snapshot_kwargs.get("repo_type"),
    )
    snapshot_path = snapshot_download(
        repo_id,
        tqdm_class=HuggingFaceSnapshotProgress,
        **snapshot_kwargs,
    )
    update_task(
        phase=post_download_phase,
        message=load_message,
        progress=HUGGINGFACE_LOAD_PROGRESS,
    )
    return snapshot_path
