from __future__ import annotations

import threading
import time
from typing import Any, Callable

TaskUpdate = Callable[..., None]

HUGGINGFACE_DOWNLOAD_PROGRESS_START = 0.02
HUGGINGFACE_DOWNLOAD_PROGRESS_END = 0.85
HUGGINGFACE_LOAD_PROGRESS = 0.92
HUGGINGFACE_PROGRESS_LOG_LIMIT = 20
HUGGINGFACE_PROGRESS_UPDATE_INTERVAL_SEC = 0.25


def preload_huggingface_snapshot(
    repo_id: str,
    *,
    cached: bool,
    update_task: TaskUpdate,
    download_message: str,
    cached_message: str,
    load_message: str,
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

    def update_byte_progress(current: float, total: float, *, force: bool = False) -> None:
        nonlocal last_progress_update, last_progress_value
        if total <= 0:
            print(f"[snapshot-progress] update_byte_progress SKIP total<=0  "
                  f"current={current}  total={total}")
            return
        current = min(max(0.0, current), total)
        ratio = min(1.0, max(0.0, current / total))
        progress = HUGGINGFACE_DOWNLOAD_PROGRESS_START + ratio * (
            HUGGINGFACE_DOWNLOAD_PROGRESS_END - HUGGINGFACE_DOWNLOAD_PROGRESS_START
        )
        now = time.monotonic()
        with progress_lock:
            should_update = (
                force
                or last_progress_value is None
                or progress >= HUGGINGFACE_DOWNLOAD_PROGRESS_END
                or progress - last_progress_value >= 0.005
                or now - last_progress_update >= HUGGINGFACE_PROGRESS_UPDATE_INTERVAL_SEC
            )
            if not should_update:
                print(f"[snapshot-progress] update_byte_progress THROTTLED  "
                      f"current={current:.0f}  total={total:.0f}  progress={progress:.4f}  "
                      f"last={last_progress_value:.4f}  delta={progress - last_progress_value:.6f}  "
                      f"force={force}")
                return
            last_progress_value = progress
            last_progress_update = now
            message = f"{download_message} ({format_bytes(current)} / {format_bytes(total)})."
            print(f"[snapshot-progress] update_byte_progress FIRE  progress={progress:.4f}  "
                  f"current={current:.0f}  total={total:.0f}  ratio={ratio:.4f}  force={force}")
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
            super().__init__(*args, **kwargs)
            if self._is_byte_progress():
                # Force disable=False so that super().update() always increments
                # self.n and super().refresh() is never a no-op.  The huggingface_hub
                # v1.x snapshot_download creates bytes_progress with total=0 and may
                # leave disable=None/True depending on the logger effective level;
                # when disabled, update() returns without touching self.n and our
                # frontend progress stays stuck at HUGGINGFACE_DOWNLOAD_PROGRESS_START
                # (2 %) forever.
                self.disable = False
                print(f"[snapshot-progress] __init__  n={self.n}  total={self.total}  "
                      f"disable_was={getattr(self, 'disable', None)}  "
                      f"unit={self._shinsekai_unit}  name={self._shinsekai_name}  "
                      f"desc={self._shinsekai_desc}")
                update_byte_progress(float(self.n), float(self.total or 0), force=True)

        def _is_byte_progress(self) -> bool:
            unit = str(self._shinsekai_unit or getattr(self, "unit", "") or "").lower()
            name = str(self._shinsekai_name or "").lower()
            desc = str(self._shinsekai_desc or getattr(self, "desc", "") or "").lower()
            return (
                unit in {"b", "ib", "byte", "bytes"}
                or name == "huggingface_hub.snapshot_download"
                or (desc.startswith("download") and isinstance(getattr(self, "total", None), (int, float)))
            )

        def refresh(self, *args: Any, **kwargs: Any) -> bool | None:
            result = super().refresh(*args, **kwargs)
            if self._is_byte_progress():
                update_byte_progress(float(self.n), float(self.total or 0), force=True)
            return result

        def update(self, n: int = 1) -> bool | None:
            previous = float(getattr(self, "n", 0) or 0)
            result = super().update(n)
            if self._is_byte_progress():
                current = float(getattr(self, "n", 0) or 0)
                if n and current <= previous:
                    current = previous + float(n)
                    self.n = current
                print(f"[snapshot-progress] update  n_delta={n}  previous={previous}  "
                      f"current={current}  total={self.total}  disable={self.disable}")
                update_byte_progress(current, float(self.total or 0))
            return result

    update_task(
        phase="download",
        message=download_message,
        progress=HUGGINGFACE_DOWNLOAD_PROGRESS_START,
        logs=push_progress_log(download_message),
    )
    snapshot_path = snapshot_download(
        repo_id,
        tqdm_class=HuggingFaceSnapshotProgress,
        **snapshot_kwargs,
    )
    update_task(
        phase="reload",
        message=load_message,
        progress=HUGGINGFACE_LOAD_PROGRESS,
    )
    return snapshot_path
