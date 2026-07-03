from __future__ import annotations

from typing import Any, Callable

TaskUpdate = Callable[..., None]

HUGGINGFACE_DOWNLOAD_PROGRESS_START = 0.02
HUGGINGFACE_DOWNLOAD_PROGRESS_END = 0.85
HUGGINGFACE_LOAD_PROGRESS = 0.92


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

    class HuggingFaceSnapshotProgress(hf_tqdm):
        def update(self, n: int = 1) -> bool | None:
            result = super().update(n)
            total = self.total or 0
            if total > 0:
                current = min(self.n, total)
                ratio = min(1.0, max(0.0, current / total))
                progress = HUGGINGFACE_DOWNLOAD_PROGRESS_START + ratio * (
                    HUGGINGFACE_DOWNLOAD_PROGRESS_END - HUGGINGFACE_DOWNLOAD_PROGRESS_START
                )
                message = f"{download_message} ({current}/{total} files)."
            else:
                progress = HUGGINGFACE_DOWNLOAD_PROGRESS_START
                message = download_message
            update_task(
                phase="download",
                message=message,
                progress=round(progress, 4),
            )
            return result

    update_task(
        phase="download",
        message=download_message,
        progress=HUGGINGFACE_DOWNLOAD_PROGRESS_START,
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
