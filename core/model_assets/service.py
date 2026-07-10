from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .downloads import preload_huggingface_snapshot

TaskUpdate = Callable[..., None]
ModelAssetSource = Literal["huggingface", "local"]


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


def _matches_required_pattern(snapshot: Path, pattern: str) -> bool:
    normalized = str(pattern or "").strip().replace("\\", "/")
    if not normalized:
        return False
    if any(marker in normalized for marker in ("*", "?", "[")):
        return any(candidate.is_file() for candidate in snapshot.glob(normalized))
    return (snapshot / Path(*normalized.split("/"))).is_file()


def _snapshot_is_complete(snapshot: Path, required_file_groups: tuple[tuple[str, ...], ...]) -> bool:
    if not snapshot.is_dir():
        return False
    if not required_file_groups:
        try:
            return any(snapshot.iterdir())
        except OSError:
            return False
    return all(
        any(_matches_required_pattern(snapshot, pattern) for pattern in alternatives)
        for alternatives in required_file_groups
    )


def find_cached_huggingface_snapshot(spec: ModelAssetSpec) -> Path | None:
    """Return the complete snapshot referenced by the cached ``main`` ref.

    Hugging Face can retain older complete snapshots after an interrupted
    update.  The runtime resolves the configured model through ``refs/main``,
    so considering an unrelated old snapshot cached would make the later model
    load download again (or fail offline).
    """

    if spec.source != "huggingface":
        return None
    try:
        from huggingface_hub import scan_cache_dir
    except ImportError:
        return None

    for root in _huggingface_cache_roots():
        try:
            cache_info = scan_cache_dir(root)
        except Exception:
            continue
        resolved_root = root.resolve(strict=False)
        for repo in cache_info.repos:
            if repo.repo_type != "model" or repo.repo_id != spec.repo_id:
                continue
            for revision in repo.revisions:
                if "main" not in revision.refs:
                    continue
                snapshot = Path(revision.snapshot_path).resolve(strict=False)
                try:
                    within_root = os.path.commonpath(
                        [str(resolved_root), str(snapshot)]
                    ) == str(resolved_root)
                except ValueError:
                    within_root = False
                if within_root and _snapshot_is_complete(
                    snapshot, spec.required_file_groups
                ):
                    return snapshot
    return None


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
        cached = bool(path and _snapshot_is_complete(path, spec.required_file_groups))
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


def download_model_asset(
    spec: ModelAssetSpec,
    *,
    update_task: TaskUpdate,
    token: str = "",
) -> dict[str, object]:
    """Ensure a model asset is cached and return its resolved status."""

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
        raise RuntimeError(f"Model download did not return a snapshot path: {spec.repo_id}")

    resolved = Path(snapshot_path).resolve(strict=False)
    if not _snapshot_is_complete(resolved, spec.required_file_groups):
        raise RuntimeError(f"Downloaded model snapshot is incomplete: {spec.repo_id}")
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


__all__ = [
    "ModelAssetSpec",
    "download_model_asset",
    "find_cached_huggingface_snapshot",
    "inspect_model_asset",
]
