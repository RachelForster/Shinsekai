from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .downloads import preload_huggingface_snapshot

TaskUpdate = Callable[..., None]
ModelAssetSource = Literal["huggingface", "local"]

_MODEL_ASSET_DOWNLOAD_LOCKS_GUARD = threading.Lock()
_MODEL_ASSET_DOWNLOAD_LOCKS: dict[str, threading.Lock] = {}


def _model_asset_download_lock(task_key: str) -> threading.Lock:
    with _MODEL_ASSET_DOWNLOAD_LOCKS_GUARD:
        return _MODEL_ASSET_DOWNLOAD_LOCKS.setdefault(task_key, threading.Lock())


@dataclass(frozen=True)
class ModelAssetSpec:
    """Description of a model asset managed by the shared download service."""

    asset_id: str
    title: str
    variant: str
    source: ModelAssetSource = "huggingface"
    repo_id: str = ""
    local_path: Path | None = None
    allow_patterns: tuple[str, ...] = ()
    required_file_groups: tuple[tuple[str, ...], ...] = ()
    snapshot_validator: Callable[[Path], bool] | None = None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id is required")
        if self.source == "huggingface" and not self.repo_id.strip():
            raise ValueError("repo_id is required for Hugging Face model assets")
        if self.source == "local" and self.local_path is None:
            raise ValueError("local_path is required for local model assets")

    @property
    def task_key(self) -> str:
        if self.source == "local":
            location = str(self.local_path.resolve(strict=False)) if self.local_path else ""
        else:
            location = self.repo_id.strip().casefold()
        return f"{self.asset_id}:{self.source}:{location}"


def _huggingface_cache_roots() -> tuple[Path, ...]:
    """Return the single hub cache root Hugging Face will actually use."""

    for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        raw = str(os.environ.get(env_name) or "").strip()
        if raw:
            return (Path(raw).expanduser().resolve(strict=False),)

    hf_home_raw = str(os.environ.get("HF_HOME") or "").strip()
    hf_home = Path(hf_home_raw).expanduser() if hf_home_raw else Path.home() / ".cache" / "huggingface"
    return ((hf_home / "hub").resolve(strict=False),)


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _matches_required_pattern(snapshot: Path, pattern: str) -> bool:
    normalized = str(pattern or "").strip().replace("\\", "/")
    if not normalized:
        return False
    if any(marker in normalized for marker in ("*", "?", "[")):
        return any(_is_nonempty_file(candidate) for candidate in snapshot.glob(normalized))
    return _is_nonempty_file(snapshot / Path(*normalized.split("/")))


def _snapshot_is_complete(
    snapshot: Path,
    required_file_groups: tuple[tuple[str, ...], ...],
    snapshot_validator: Callable[[Path], bool] | None = None,
) -> bool:
    if not snapshot.is_dir():
        return False
    try:
        files_complete = (
            all(
                any(_matches_required_pattern(snapshot, pattern) for pattern in alternatives)
                for alternatives in required_file_groups
            )
            if required_file_groups
            else any(snapshot.iterdir())
        )
        return files_complete and (
            snapshot_validator is None or bool(snapshot_validator(snapshot))
        )
    except Exception:
        return False


def _main_huggingface_snapshots(spec: ModelAssetSpec) -> tuple[Path, ...]:
    if spec.source != "huggingface":
        return ()
    try:
        from huggingface_hub.file_download import repo_folder_name
    except ImportError:
        return ()

    snapshots: list[Path] = []
    for root in _huggingface_cache_roots():
        try:
            resolved_root = root.resolve(strict=False)
            repo_dir = (
                resolved_root
                / repo_folder_name(repo_id=spec.repo_id, repo_type="model")
            ).resolve(strict=False)
            if os.path.normcase(
                os.path.commonpath([str(resolved_root), str(repo_dir)])
            ) != os.path.normcase(str(resolved_root)):
                continue
            revision = (repo_dir / "refs" / "main").read_text(encoding="utf-8").strip()
            if not revision or revision in {".", ".."} or "/" in revision or "\\" in revision:
                continue
            snapshots_dir = (repo_dir / "snapshots").resolve(strict=False)
            snapshot = snapshots_dir / revision
            resolved_snapshot = snapshot.resolve(strict=False)
            if os.path.normcase(
                os.path.commonpath([str(snapshots_dir), str(resolved_snapshot)])
            ) == os.path.normcase(str(snapshots_dir)):
                snapshots.append(snapshot)
        except (OSError, TypeError, ValueError):
            continue
    return tuple(snapshots)


def find_cached_huggingface_snapshot(spec: ModelAssetSpec) -> Path | None:
    """Return the complete snapshot referenced by the cached ``main`` ref.

    Hugging Face can retain older complete snapshots after an interrupted
    update.  The runtime resolves the configured model through ``refs/main``,
    so considering an unrelated old snapshot cached would make the later model
    load download again (or fail offline).
    """

    for snapshot in _main_huggingface_snapshots(spec):
        if _snapshot_is_complete(
            snapshot,
            spec.required_file_groups,
            spec.snapshot_validator,
        ):
            return snapshot
    return None


def _remove_invalid_main_snapshots(spec: ModelAssetSpec) -> bool:
    """Remove only invalid snapshots selected by the cached ``main`` ref.

    ``snapshot_download(force_download=True)`` refreshes blobs but deliberately
    leaves an existing snapshot pointer in place.  A regular file left by an
    interrupted or external cache write would therefore survive every retry.
    Removing the invalid snapshot first lets Hugging Face rebuild its pointers
    while preserving the shared blob cache.
    """

    removed = False
    for snapshot in _main_huggingface_snapshots(spec):
        if not snapshot.exists() or _snapshot_is_complete(
            snapshot,
            spec.required_file_groups,
            spec.snapshot_validator,
        ):
            continue
        if snapshot.is_symlink():
            snapshot.unlink()
        elif snapshot.is_dir():
            shutil.rmtree(snapshot)
        else:
            snapshot.unlink()
        removed = True
    return removed


def inspect_model_asset(spec: ModelAssetSpec) -> dict[str, object]:
    """Return the cache/download state consumed by model download UIs."""

    result: dict[str, object] = {
        "assetId": spec.asset_id,
        "variant": spec.variant,
        "title": spec.title,
        "source": spec.source,
        "cached": False,
        "downloadable": spec.source == "huggingface",
    }
    if spec.source == "local":
        path = spec.local_path.resolve(strict=False) if spec.local_path else None
        cached = bool(
            path
            and _snapshot_is_complete(
                path,
                spec.required_file_groups,
                spec.snapshot_validator,
            )
        )
        result["cached"] = cached
        if path is not None:
            result["path"] = str(path)
        return result

    result["repoId"] = spec.repo_id
    snapshot = find_cached_huggingface_snapshot(spec)
    if snapshot is not None:
        result["cached"] = True
        result["path"] = str(snapshot)
    return result


def _download_model_asset_unlocked(
    spec: ModelAssetSpec,
    *,
    update_task: TaskUpdate,
    token: str = "",
) -> dict[str, object]:
    current = inspect_model_asset(spec)
    if spec.source == "local":
        if not current["cached"]:
            raise ValueError(f"Local model directory does not exist: {current.get('path', '')}")
        return {**current, "downloaded": False}

    if current["cached"]:
        update_task(
            phase="verify",
            message=f"{spec.title} is already cached.",
            progress=0.92,
        )
        return {**current, "downloaded": False}

    snapshot_kwargs: dict[str, object] = {}
    main_snapshots = _main_huggingface_snapshots(spec)
    if main_snapshots:
        # The active snapshot exists but failed validation. Redownload the
        # complete allowed artifact set and rebuild its snapshot pointers so no
        # partial or corrupt file survives.
        _remove_invalid_main_snapshots(spec)
        snapshot_kwargs["force_download"] = True
    if spec.allow_patterns:
        snapshot_kwargs["allow_patterns"] = list(spec.allow_patterns)
    if token.strip():
        snapshot_kwargs["token"] = token.strip()

    snapshot_path = preload_huggingface_snapshot(
        spec.repo_id,
        cached=False,
        update_task=update_task,
        download_message=f"Downloading {spec.title}",
        cached_message=f"{spec.title} is already cached.",
        load_message=f"Verifying {spec.title}.",
        post_download_phase="verify",
        **snapshot_kwargs,
    )
    if not snapshot_path:
        raise RuntimeError(
            f"Model download did not return a snapshot path: {spec.repo_id}"
        )

    resolved = Path(snapshot_path).resolve(strict=False)
    if not _snapshot_is_complete(
        resolved,
        spec.required_file_groups,
        spec.snapshot_validator,
    ):
        raise RuntimeError(
            f"Downloaded model snapshot is incomplete: {spec.repo_id}"
        )
    return {
        "assetId": spec.asset_id,
        "variant": spec.variant,
        "title": spec.title,
        "source": spec.source,
        "repoId": spec.repo_id,
        "path": str(resolved),
        "cached": True,
        "downloadable": True,
        "downloaded": True,
    }


def download_model_asset(
    spec: ModelAssetSpec,
    *,
    update_task: TaskUpdate,
    token: str = "",
) -> dict[str, object]:
    """Ensure a model asset is cached and return its resolved status.

    Calls for the same asset are serialized across UI and runtime entry points
    so validation and cleanup cannot race an in-progress snapshot download.
    """

    with _model_asset_download_lock(spec.task_key):
        return _download_model_asset_unlocked(spec, update_task=update_task, token=token)


__all__ = [
    "ModelAssetSpec",
    "download_model_asset",
    "find_cached_huggingface_snapshot",
    "inspect_model_asset",
]
