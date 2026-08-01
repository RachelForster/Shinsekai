from __future__ import annotations

import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from sdk.file_transactions import (
    read_text_without_links,
    remove_directory_without_links,
    remove_file_without_links,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from core.paths import (
    _metadata_is_link_or_reparse_point,
    managed_project_storage,
    path_is_within,
    project_root,
    resolve_project_output_path,
    safe_path_component,
    user_home_directory,
)

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


def active_huggingface_hub_cache_root(
    *,
    root: Path | None = None,
) -> Path:
    """Return the one hub cache root used by readiness checks and downloads.

    Environment-variable presence is authoritative.  In particular, an empty
    current variable must not fall through to a populated legacy variable or
    to Hugging Face's cwd-relative interpretation of an empty cache path.
    """

    project = project_root() if root is None else root
    for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if env_name not in os.environ:
            continue
        raw = os.environ[env_name]
        if not raw:
            raise ValueError(f"{env_name} must not be empty")
        return resolve_project_output_path(raw, root=project)

    if "HF_HOME" in os.environ:
        hf_home_raw = os.environ["HF_HOME"]
        if not hf_home_raw:
            raise ValueError("HF_HOME must not be empty")
        hf_home = resolve_project_output_path(hf_home_raw, root=project)
    else:
        try:
            home = user_home_directory()
        except (KeyError, OSError, RuntimeError, ValueError):
            hf_home = managed_project_storage("data/cache/huggingface", root=project)
        else:
            hf_home = home / ".cache" / "huggingface"
    # A project-owned ``HF_HOME`` must not regain an escape through a linked
    # ``hub`` child created after the parent was validated.
    return resolve_project_output_path(hf_home / "hub", root=project)


def _huggingface_cache_roots(
    *,
    root: Path | None = None,
) -> tuple[Path, ...]:
    """Backward-compatible tuple wrapper around the single active cache root."""

    return (active_huggingface_hub_cache_root(root=root),)


def _normalized_required_pattern(pattern: str) -> str:
    normalized = str(pattern or "").strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        return ""
    return normalized


def _pattern_matches_relative_path(relative: Path, pattern: str) -> bool:
    normalized = _normalized_required_pattern(pattern)
    if not normalized:
        return False
    relative_text = relative.as_posix()
    if not any(marker in normalized for marker in ("*", "?", "[")):
        return relative_text == normalized
    if "/" not in normalized and len(relative.parts) != 1:
        return False
    return relative.match(normalized)


def _snapshot_regular_paths(
    snapshot: Path,
    *,
    allowed_link_root: Path,
    expected_snapshot_identity: os.stat_result | None = None,
) -> set[Path] | None:
    """Inventory one stable model tree, allowing only bounded file links."""

    try:
        snapshot, snapshot_identity, root_entries = (
            snapshot_directory_entries_without_links(
                snapshot,
                field="model snapshot directory",
            )
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError):
        return None
    allowed_root = allowed_link_root.resolve(strict=False)
    if (
        expected_snapshot_identity is not None
        and not os.path.samestat(
            expected_snapshot_identity,
            snapshot_identity,
        )
    ):
        return None
    regular_paths: set[Path] = set()
    observed_leaves: list[
        tuple[
            Path,
            os.stat_result,
            Path | None,
            os.stat_result | None,
        ]
    ] = []
    pending: list[
        tuple[
            Path,
            Path,
            os.stat_result,
            list[tuple[Path, os.stat_result]] | None,
        ]
    ] = [(snapshot, Path(), snapshot_identity, root_entries)]
    try:
        while pending:
            directory, relative_dir, expected_identity, prefetched = pending.pop()
            if prefetched is None:
                directory, directory_identity, entries = (
                    snapshot_directory_entries_without_links(
                        directory,
                        field="model snapshot subdirectory",
                    )
                )
                if not os.path.samestat(
                    expected_identity,
                    directory_identity,
                ):
                    raise PermissionError(
                        f"model snapshot directory identity changed: {directory}"
                    )
            else:
                directory_identity = expected_identity
                entries = prefetched
            for path, metadata in entries:
                relative = relative_dir / path.name
                if _metadata_is_link_or_reparse_point(metadata):
                    try:
                        resolved = path.resolve(strict=True)
                        target_identity = resolved.stat()
                    except OSError:
                        continue
                    if (
                        not path_is_within(resolved, allowed_root)
                        or not stat.S_ISREG(target_identity.st_mode)
                        or target_identity.st_size <= 0
                    ):
                        continue
                    regular_paths.add(relative)
                    observed_leaves.append(
                        (path, metadata, resolved, target_identity)
                    )
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(
                        (path, relative, metadata, None)
                    )
                    continue
                if stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0:
                    regular_paths.add(relative)
                    observed_leaves.append(
                        (path, metadata, None, None)
                    )
            require_directory_identity(
                directory,
                directory_identity,
                field="model snapshot directory",
            )
            require_directory_identity(
                snapshot,
                snapshot_identity,
                field="model snapshot directory",
            )

        for path, identity, resolved, target_identity in observed_leaves:
            current_identity = path.lstat()
            if not os.path.samestat(identity, current_identity):
                raise PermissionError(
                    f"model snapshot file identity changed: {path}"
                )
            if resolved is not None:
                current_resolved = path.resolve(strict=True)
                current_target_identity = current_resolved.stat()
                if (
                    current_resolved != resolved
                    or target_identity is None
                    or not os.path.samestat(
                        target_identity,
                        current_target_identity,
                    )
                ):
                    raise PermissionError(
                        f"model snapshot link target changed: {path}"
                    )
        require_directory_identity(
            snapshot,
            snapshot_identity,
            field="model snapshot directory",
        )
    except (OSError, PermissionError, ValueError):
        return None
    return regular_paths


def _snapshot_is_complete(
    snapshot: Path,
    required_file_groups: tuple[tuple[str, ...], ...],
    snapshot_validator: Callable[[Path], bool] | None = None,
    *,
    allowed_link_root: Path | None = None,
    expected_snapshot_identity: os.stat_result | None = None,
) -> bool:
    regular_paths = _snapshot_regular_paths(
        snapshot,
        allowed_link_root=(
            snapshot
            if allowed_link_root is None
            else allowed_link_root
        ),
        expected_snapshot_identity=expected_snapshot_identity,
    )
    if regular_paths is None:
        return False
    files_complete = (
        all(
            any(
                any(
                    _pattern_matches_relative_path(relative, pattern)
                    for relative in regular_paths
                )
                for pattern in alternatives
            )
            for alternatives in required_file_groups
        )
        if required_file_groups
        else bool(regular_paths)
    )
    if not files_complete:
        return False
    if snapshot_validator is None:
        return True
    try:
        return bool(snapshot_validator(snapshot))
    except Exception:
        return False


def _main_huggingface_snapshots(
    spec: ModelAssetSpec,
    *,
    root: Path | None = None,
) -> tuple[Path, ...]:
    """Return only the active ``main`` snapshot under the selected cache root."""

    if spec.source != "huggingface":
        return ()
    try:
        from huggingface_hub.file_download import repo_folder_name
    except ImportError:
        return ()

    try:
        cache_root = active_huggingface_hub_cache_root(root=root)
        repo_name = safe_path_component(
            repo_folder_name(repo_id=spec.repo_id, repo_type="model"),
            field="Hugging Face repository cache directory",
        )
        repo_dir = resolve_project_output_path(repo_name, root=cache_root)
        revision = safe_path_component(
            read_text_without_links(repo_dir / "refs" / "main").strip(),
            field="Hugging Face main revision",
        )
        snapshots_dir = resolve_project_output_path(
            repo_dir / "snapshots",
            root=cache_root,
        )
        snapshot = resolve_project_output_path(
            snapshots_dir / revision,
            root=cache_root,
        )
    except (FileNotFoundError, ImportError, OSError, PermissionError, TypeError, ValueError):
        return ()
    return (snapshot,)


def find_cached_huggingface_snapshot(
    spec: ModelAssetSpec,
    *,
    root: Path | None = None,
) -> Path | None:
    """Return the complete snapshot referenced by the cached ``main`` ref.

    Hugging Face can retain older complete snapshots after an interrupted
    update.  The runtime resolves the configured model through ``refs/main``,
    so considering an unrelated old snapshot cached would make the later model
    load download again (or fail offline).
    """

    cache_root = active_huggingface_hub_cache_root(root=root)
    for snapshot in _main_huggingface_snapshots(spec, root=root):
        if _snapshot_is_complete(
            snapshot,
            spec.required_file_groups,
            spec.snapshot_validator,
            allowed_link_root=cache_root,
        ):
            return snapshot
    return None


def _remove_invalid_main_snapshots(
    spec: ModelAssetSpec,
    *,
    root: Path | None = None,
) -> bool:
    """Remove only invalid snapshots selected by the cached ``main`` ref.

    ``snapshot_download(force_download=True)`` refreshes blobs but deliberately
    leaves an existing snapshot pointer in place.  A regular file left by an
    interrupted or external cache write would therefore survive every retry.
    Removing the invalid snapshot first lets Hugging Face rebuild its pointers
    while preserving the shared blob cache.
    """

    removed = False
    cache_root = active_huggingface_hub_cache_root(root=root)
    for snapshot in _main_huggingface_snapshots(spec, root=root):
        try:
            metadata = snapshot.lstat()
        except FileNotFoundError:
            continue
        if _snapshot_is_complete(
            snapshot,
            spec.required_file_groups,
            spec.snapshot_validator,
            allowed_link_root=cache_root,
            expected_snapshot_identity=metadata,
        ):
            continue
        if _metadata_is_link_or_reparse_point(metadata):
            raise PermissionError(
                f"invalid model snapshot is a symbolic link or reparse point: {snapshot}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            remove_directory_without_links(
                snapshot,
                expected_identity=metadata,
            )
        elif stat.S_ISREG(metadata.st_mode):
            remove_file_without_links(
                snapshot,
                expected_identity=metadata,
            )
        else:
            raise PermissionError(f"invalid model snapshot has an unsafe type: {snapshot}")
        removed = True
    return removed


def inspect_model_asset(
    spec: ModelAssetSpec,
    *,
    root: Path | None = None,
) -> dict[str, object]:
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
                allowed_link_root=path,
            )
        )
        result["cached"] = cached
        if path is not None:
            result["path"] = str(path)
        return result

    result["repoId"] = spec.repo_id
    snapshot = find_cached_huggingface_snapshot(spec, root=root)
    if snapshot is not None:
        result["cached"] = True
        result["path"] = str(snapshot)
    return result


def _download_model_asset_unlocked(
    spec: ModelAssetSpec,
    *,
    update_task: TaskUpdate,
    token: str = "",
    root: Path | None = None,
) -> dict[str, object]:
    """Ensure a model asset is cached and return its resolved status."""

    current = inspect_model_asset(spec, root=root)
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

    cache_root = active_huggingface_hub_cache_root(root=root)
    snapshot_kwargs: dict[str, object] = {"cache_dir": str(cache_root)}
    main_snapshots = _main_huggingface_snapshots(spec, root=root)
    if main_snapshots:
        # The active snapshot exists but failed validation. Redownload the
        # complete allowed artifact set and rebuild its snapshot pointers so no
        # partial or corrupt file survives.
        _remove_invalid_main_snapshots(spec, root=root)
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
    if not path_is_within(resolved, cache_root):
        raise RuntimeError(
            f"Downloaded model snapshot is outside the active cache root: {spec.repo_id}"
        )
    if not _snapshot_is_complete(
        resolved,
        spec.required_file_groups,
        spec.snapshot_validator,
        allowed_link_root=cache_root,
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
    root: Path | None = None,
) -> dict[str, object]:
    """Ensure a model asset is cached and return its resolved status.

    Calls for the same asset are serialized across UI and runtime entry points
    so validation and cleanup cannot race an in-progress snapshot download.
    """

    with _model_asset_download_lock(spec.task_key):
        return _download_model_asset_unlocked(
            spec,
            update_task=update_task,
            token=token,
            root=root,
        )


__all__ = [
    "ModelAssetSpec",
    "active_huggingface_hub_cache_root",
    "download_model_asset",
    "find_cached_huggingface_snapshot",
    "inspect_model_asset",
]
