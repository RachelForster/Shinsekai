from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .downloads import preload_huggingface_snapshot

TaskUpdate = Callable[..., None]
ModelAssetSource = Literal["huggingface", "local"]

_REVISION_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_COMMIT_HASH_RE = re.compile(r"^[0-9a-f]{40}$")

_MODEL_ASSET_DOWNLOAD_LOCKS_GUARD = threading.Lock()
_MODEL_ASSET_DOWNLOAD_LOCKS: dict[str, threading.Lock] = {}


def _validate_revision(revision: str) -> str:
    cleaned = str(revision or "").strip()
    if not cleaned:
        return ""
    if (
        len(cleaned) > 128
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned)
        or ".." in cleaned.split("/")
        or not _REVISION_RE.fullmatch(cleaned)
    ):
        raise ValueError(f"Invalid Hugging Face revision: {revision!r}")
    return cleaned


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
    revision: str = ""
    local_path: Path | None = None
    allow_patterns: tuple[str, ...] = ()
    required_file_groups: tuple[tuple[str, ...], ...] = ()
    snapshot_validator: Callable[[Path], bool] | None = None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id is required")
        cleaned_revision = _validate_revision(self.revision)
        if cleaned_revision != self.revision:
            object.__setattr__(self, "revision", cleaned_revision)
        if self.source == "huggingface" and not self.repo_id.strip():
            raise ValueError("repo_id is required for Hugging Face model assets")
        if self.source == "local":
            if self.local_path is None:
                raise ValueError("local_path is required for local model assets")
            if self.revision:
                raise ValueError("revision is not supported for local model assets")

    @property
    def task_key(self) -> str:
        if self.source == "local":
            location = str(self.local_path.resolve(strict=False)) if self.local_path else ""
            return f"{self.asset_id}:{self.source}:{location}"
        location = self.repo_id.strip().casefold()
        if self.revision:
            location = f"{location}@{self.revision}"
        base = f"{self.asset_id}:{self.source}:{location}"
        if self.asset_id == "huggingface.repo" and (
            self.allow_patterns or self.required_file_groups
        ):
            scope_payload = json.dumps(
                {
                    "allow": list(self.allow_patterns),
                    "required": [list(group) for group in self.required_file_groups],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(scope_payload.encode("utf-8")).hexdigest()[:12]
            return f"{base}#scope={digest}"
        return base

    @property
    def lock_key(self) -> str:
        if self.source == "local":
            location = str(self.local_path.resolve(strict=False)) if self.local_path else ""
            return f"local:{location}"
        location = self.repo_id.strip().casefold()
        if self.revision:
            location = f"{location}@{self.revision}"
        return f"huggingface:{location}"


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


def _has_glob_wildcard(pattern: str) -> bool:
    return any(marker in pattern for marker in ("*", "?", "["))


def _matches_required_pattern(snapshot: Path, pattern: str) -> bool:
    normalized = str(pattern or "").strip().replace("\\", "/")
    if not normalized:
        return False
    if _has_glob_wildcard(normalized):
        return any(_is_nonempty_file(candidate) for candidate in snapshot.glob(normalized))
    return _is_nonempty_file(snapshot / Path(*normalized.split("/")))


def _is_safe_relative_repo_path(rel_path: str) -> bool:
    normalized = str(rel_path or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return False
    parts = normalized.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _snapshot_file_matches_entry(
    snapshot: Path,
    rel_path: str,
    expected_size: int | None,
) -> bool:
    if not _is_safe_relative_repo_path(rel_path):
        return False
    target = snapshot / Path(*rel_path.replace("\\", "/").split("/"))
    try:
        if not target.is_file():
            return False
        actual_size = target.stat().st_size
    except OSError:
        return False
    if expected_size is not None:
        return actual_size == expected_size
    return actual_size > 0


def _list_snapshot_relative_files(snapshot: Path) -> tuple[str, ...]:
    if not snapshot.is_dir():
        return ()
    files: list[str] = []
    try:
        for candidate in snapshot.rglob("*"):
            if _is_nonempty_file(candidate):
                rel = candidate.relative_to(snapshot).as_posix()
                if _is_safe_relative_repo_path(rel):
                    files.append(rel)
    except OSError:
        return ()
    files.sort()
    return tuple(files)


def _filter_paths_by_patterns(
    paths: tuple[str, ...] | list[str],
    allow_patterns: tuple[str, ...],
) -> tuple[str, ...]:
    if not allow_patterns:
        return tuple(paths)
    normalized_patterns = [
        str(pattern).strip().replace("\\", "/")
        for pattern in allow_patterns
        if str(pattern).strip()
    ]
    if not normalized_patterns:
        return tuple(paths)
    try:
        from huggingface_hub.utils import filter_repo_objects

        return tuple(filter_repo_objects(items=list(paths), allow_patterns=normalized_patterns))
    except ImportError:
        return tuple(
            item
            for item in paths
            if any(fnmatch.fnmatch(item, pat) for pat in normalized_patterns)
        )


def _filter_manifest_entries(
    entries: tuple[tuple[str, int | None], ...],
    allow_patterns: tuple[str, ...],
) -> tuple[tuple[str, int | None], ...]:
    if not allow_patterns:
        return entries
    selected = set(_filter_paths_by_patterns([path for path, _ in entries], allow_patterns))
    return tuple((path, size) for path, size in entries if path in selected)


def _scope_key_for_patterns(allow_patterns: tuple[str, ...]) -> str:
    normalized = tuple(
        str(pattern).strip().replace("\\", "/")
        for pattern in allow_patterns
        if str(pattern).strip()
    )
    return json.dumps(normalized, separators=(",", ":"))


def _manifest_path_for_snapshot(snapshot: Path) -> Path | None:
    try:
        if snapshot.parent.name != "snapshots":
            return None
        revision = snapshot.name
        if not revision or revision in {".", ".."} or "/" in revision or "\\" in revision:
            return None
        repo_dir = snapshot.parent.parent
        manifest_dir = (repo_dir / ".shinsekai_manifests").resolve(strict=False)
        manifest_file = (manifest_dir / f"{revision}.json").resolve(strict=False)
        if os.path.normcase(
            os.path.commonpath([str(manifest_dir), str(manifest_file)])
        ) != os.path.normcase(str(manifest_dir)):
            return None
        return manifest_file
    except (OSError, TypeError, ValueError):
        return None


def _read_snapshot_sidecar(snapshot: Path) -> dict[str, object]:
    manifest_file = _manifest_path_for_snapshot(snapshot)
    if manifest_file is None or not manifest_file.is_file():
        return {}
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_snapshot_sidecar(snapshot: Path, payload: dict[str, object]) -> None:
    manifest_file = _manifest_path_for_snapshot(snapshot)
    if manifest_file is None:
        return
    try:
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        return


def _fetch_huggingface_revision_files(
    repo_id: str,
    *,
    revision: str | None = None,
    token: str = "",
) -> tuple[tuple[str, int | None], ...] | None:
    """Fetch the file manifest (relative paths and optional byte sizes) for a revision."""

    try:
        from huggingface_hub import HfApi

        clean_token = str(token or "").strip() or None
        api = HfApi(token=clean_token)
        info = api.model_info(
            repo_id,
            revision=revision or None,
            timeout=5.0,
            token=clean_token,
        )
        siblings = getattr(info, "siblings", None)
        if siblings is None:
            return None
        entries: list[tuple[str, int | None]] = []
        for sibling in siblings:
            rfilename = (
                str(getattr(sibling, "rfilename", "") or "").strip().replace("\\", "/")
            )
            if not _is_safe_relative_repo_path(rfilename):
                continue
            raw_size = getattr(sibling, "size", None)
            size = int(raw_size) if isinstance(raw_size, int) and raw_size >= 0 else None
            entries.append((rfilename, size))
        return tuple(entries)
    except Exception:
        return None


def _get_or_fetch_revision_manifest(
    spec: ModelAssetSpec,
    snapshot: Path,
    *,
    token: str = "",
) -> tuple[tuple[str, int | None], ...] | None:
    sidecar = _read_snapshot_sidecar(snapshot)
    cached_entries = sidecar.get("repo_files")
    if isinstance(cached_entries, list) and cached_entries:
        parsed: list[tuple[str, int | None]] = []
        for item in cached_entries:
            if isinstance(item, dict):
                rel = str(item.get("path") or "").strip().replace("\\", "/")
                raw_sz = item.get("size")
                sz = int(raw_sz) if isinstance(raw_sz, int) and raw_sz >= 0 else None
                if _is_safe_relative_repo_path(rel):
                    parsed.append((rel, sz))
        if parsed:
            return tuple(parsed)

    revision_query = (
        snapshot.name
        if _COMMIT_HASH_RE.fullmatch(snapshot.name)
        else (spec.revision or None)
    )
    fetched = _fetch_huggingface_revision_files(
        spec.repo_id,
        revision=revision_query,
        token=token,
    )
    if fetched is not None and fetched:
        updated = dict(sidecar)
        updated["repo_files"] = [
            {"path": rel, "size": sz} for rel, sz in fetched
        ]
        _write_snapshot_sidecar(snapshot, updated)
    return fetched


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


def _huggingface_snapshot_is_complete(
    spec: ModelAssetSpec,
    snapshot: Path,
    *,
    token: str = "",
) -> bool:
    if not snapshot.is_dir():
        return False
    if spec.required_file_groups:
        return _snapshot_is_complete(
            snapshot,
            spec.required_file_groups,
            spec.snapshot_validator,
        )

    try:
        if spec.allow_patterns:
            # Fast fail without network if nothing in snapshot matches any requested pattern.
            if not any(
                _matches_required_pattern(snapshot, pattern)
                for pattern in spec.allow_patterns
            ):
                return False

            entries = _get_or_fetch_revision_manifest(spec, snapshot, token=token)
            if entries is not None:
                expected = _filter_manifest_entries(entries, spec.allow_patterns)
                files_complete = bool(expected) and all(
                    _snapshot_file_matches_entry(snapshot, rel, sz)
                    for rel, sz in expected
                )
                return files_complete and (
                    spec.snapshot_validator is None or bool(spec.snapshot_validator(snapshot))
                )

            sidecar = _read_snapshot_sidecar(snapshot)
            full_files = sidecar.get("full_snapshot_files")
            if isinstance(full_files, list) and full_files:
                expected_paths = _filter_paths_by_patterns(
                    [str(item) for item in full_files],
                    spec.allow_patterns,
                )
                files_complete = bool(expected_paths) and all(
                    _snapshot_file_matches_entry(snapshot, rel, None)
                    for rel in expected_paths
                )
                return files_complete and (
                    spec.snapshot_validator is None or bool(spec.snapshot_validator(snapshot))
                )

            completed_scopes = sidecar.get("completed_scopes")
            scope_key = _scope_key_for_patterns(spec.allow_patterns)
            if isinstance(completed_scopes, dict):
                recorded_scope = completed_scopes.get(scope_key)
                if isinstance(recorded_scope, list) and recorded_scope:
                    files_complete = all(
                        _snapshot_file_matches_entry(snapshot, str(rel), None)
                        for rel in recorded_scope
                    )
                    return files_complete and (
                        spec.snapshot_validator is None
                        or bool(spec.snapshot_validator(snapshot))
                    )

            # Offline fallback: only exact literal file requests (no wildcards)
            # can be proven complete without a repository manifest.
            all_literal = all(
                not _has_glob_wildcard(str(pattern).strip().replace("\\", "/"))
                for pattern in spec.allow_patterns
                if str(pattern).strip()
            )
            if not all_literal:
                return False
            files_complete = all(
                _matches_required_pattern(snapshot, pattern)
                for pattern in spec.allow_patterns
            )
            return files_complete and (
                spec.snapshot_validator is None or bool(spec.snapshot_validator(snapshot))
            )

        # Full repository request without required_file_groups: verify against
        # the revision's file manifest so partial single-file caches never pass.
        if not any(snapshot.iterdir()):
            return False

        entries = _get_or_fetch_revision_manifest(spec, snapshot, token=token)
        if entries is not None:
            files_complete = bool(entries) and all(
                _snapshot_file_matches_entry(snapshot, rel, sz)
                for rel, sz in entries
            )
            return files_complete and (
                spec.snapshot_validator is None or bool(spec.snapshot_validator(snapshot))
            )

        sidecar = _read_snapshot_sidecar(snapshot)
        full_files = sidecar.get("full_snapshot_files")
        if isinstance(full_files, list) and full_files:
            files_complete = all(
                _snapshot_file_matches_entry(snapshot, str(rel), None)
                for rel in full_files
            )
            return files_complete and (
                spec.snapshot_validator is None or bool(spec.snapshot_validator(snapshot))
            )
        return False
    except Exception:
        return False


def _verify_and_record_downloaded_snapshot(
    spec: ModelAssetSpec,
    resolved: Path,
    *,
    token: str = "",
) -> bool:
    if spec.required_file_groups:
        return _snapshot_is_complete(
            resolved,
            spec.required_file_groups,
            spec.snapshot_validator,
        )

    entries = _get_or_fetch_revision_manifest(spec, resolved, token=token)
    if entries is not None:
        if not _huggingface_snapshot_is_complete(spec, resolved, token=token):
            return False
        sidecar = _read_snapshot_sidecar(resolved)
        if spec.allow_patterns:
            matched = [rel for rel, _ in _filter_manifest_entries(entries, spec.allow_patterns)]
            scopes = dict(sidecar.get("completed_scopes") or {}) if isinstance(sidecar.get("completed_scopes"), dict) else {}
            scopes[_scope_key_for_patterns(spec.allow_patterns)] = matched
            sidecar["completed_scopes"] = scopes
        else:
            sidecar["full_snapshot_files"] = [rel for rel, _ in entries]
        _write_snapshot_sidecar(resolved, sidecar)
        return True

    present_files = _list_snapshot_relative_files(resolved)
    if not present_files:
        return False
    if spec.allow_patterns:
        matched_files = _filter_paths_by_patterns(present_files, spec.allow_patterns)
        if not matched_files:
            return False
        if spec.snapshot_validator is not None and not bool(spec.snapshot_validator(resolved)):
            return False
        sidecar = _read_snapshot_sidecar(resolved)
        scopes = dict(sidecar.get("completed_scopes") or {}) if isinstance(sidecar.get("completed_scopes"), dict) else {}
        scopes[_scope_key_for_patterns(spec.allow_patterns)] = list(matched_files)
        sidecar["completed_scopes"] = scopes
        _write_snapshot_sidecar(resolved, sidecar)
        return True

    if spec.snapshot_validator is not None and not bool(spec.snapshot_validator(resolved)):
        return False
    sidecar = _read_snapshot_sidecar(resolved)
    sidecar["full_snapshot_files"] = list(present_files)
    _write_snapshot_sidecar(resolved, sidecar)
    return True


def _main_huggingface_snapshots(spec: ModelAssetSpec) -> tuple[Path, ...]:
    if spec.source != "huggingface":
        return ()
    try:
        from huggingface_hub.file_download import repo_folder_name
    except ImportError:
        return ()

    ref_name = spec.revision or "main"
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
            snapshots_dir = (repo_dir / "snapshots").resolve(strict=False)
            refs_dir = (repo_dir / "refs").resolve(strict=False)
            ref_file = (refs_dir / Path(*ref_name.split("/"))).resolve(strict=False)
            revision = ""
            if (
                os.path.normcase(os.path.commonpath([str(refs_dir), str(ref_file)]))
                == os.path.normcase(str(refs_dir))
                and ref_file.is_file()
            ):
                revision = ref_file.read_text(encoding="utf-8").strip()
            elif _COMMIT_HASH_RE.fullmatch(ref_name):
                revision = ref_name
            if not revision or revision in {".", ".."} or "/" in revision or "\\" in revision:
                continue
            snapshot = snapshots_dir / revision
            resolved_snapshot = snapshot.resolve(strict=False)
            if os.path.normcase(
                os.path.commonpath([str(snapshots_dir), str(resolved_snapshot)])
            ) == os.path.normcase(str(snapshots_dir)):
                snapshots.append(snapshot)
        except (OSError, TypeError, ValueError):
            continue
    return tuple(snapshots)


def find_cached_huggingface_snapshot(
    spec: ModelAssetSpec,
    *,
    token: str = "",
) -> Path | None:
    """Return the complete snapshot referenced by the target revision ref.

    Hugging Face can retain older complete snapshots after an interrupted
    update.  The runtime resolves the configured model through ``refs/main``
    (or ``refs/<revision>``), so considering an unrelated old snapshot cached
    would make the later model load download again (or fail offline).
    """

    for snapshot in _main_huggingface_snapshots(spec):
        if _huggingface_snapshot_is_complete(spec, snapshot, token=token):
            return snapshot
    return None


def _remove_invalid_main_snapshots(
    spec: ModelAssetSpec,
    *,
    token: str = "",
) -> bool:
    """Remove only invalid snapshots selected by the target revision ref.

    ``snapshot_download(force_download=True)`` refreshes blobs but deliberately
    leaves an existing snapshot pointer in place.  A regular file left by an
    interrupted or external cache write would therefore survive every retry.
    Removing the invalid snapshot first lets Hugging Face rebuild its pointers
    while preserving the shared blob cache.
    """

    removed = False
    for snapshot in _main_huggingface_snapshots(spec):
        if not snapshot.exists() or _huggingface_snapshot_is_complete(
            spec,
            snapshot,
            token=token,
        ):
            continue
        if snapshot.is_symlink():
            snapshot.unlink()
        elif snapshot.is_dir():
            shutil.rmtree(snapshot)
        else:
            snapshot.unlink()
        sidecar = _read_snapshot_sidecar(snapshot)
        if sidecar:
            cleaned = {k: v for k, v in sidecar.items() if k == "repo_files"}
            _write_snapshot_sidecar(snapshot, cleaned)
        removed = True
    return removed


def _cleanup_broken_scoped_snapshot_entries(
    snapshots: tuple[Path, ...],
    allow_patterns: tuple[str, ...],
) -> bool:
    """Remove non-directory snapshots or empty files matching scoped patterns without wiping valid sibling files."""

    cleaned = False
    for snapshot in snapshots:
        if not snapshot.exists() and not snapshot.is_symlink():
            continue
        if snapshot.is_symlink() or not snapshot.is_dir():
            snapshot.unlink()
            cleaned = True
            continue
        for pattern in allow_patterns:
            normalized = str(pattern or "").strip().replace("\\", "/")
            if not normalized:
                continue
            candidates = (
                list(snapshot.glob(normalized))
                if _has_glob_wildcard(normalized)
                else [snapshot / Path(*normalized.split("/"))]
            )
            for candidate in candidates:
                try:
                    if candidate.is_symlink() and not candidate.exists():
                        candidate.unlink()
                        cleaned = True
                    elif candidate.is_file() and candidate.stat().st_size == 0:
                        candidate.unlink()
                        cleaned = True
                except OSError:
                    continue
    return cleaned


def inspect_model_asset(
    spec: ModelAssetSpec,
    *,
    token: str = "",
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
            )
        )
        result["cached"] = cached
        if path is not None:
            result["path"] = str(path)
        return result

    result["repoId"] = spec.repo_id
    if spec.revision:
        result["revision"] = spec.revision
    snapshot = find_cached_huggingface_snapshot(spec, token=token)
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
    current = inspect_model_asset(spec, token=token)
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
        if spec.required_file_groups or not spec.allow_patterns:
            # The active snapshot exists but failed validation for a full-asset
            # or full-repo request. Redownload the complete allowed artifact set
            # and rebuild its snapshot pointers so no partial or corrupt file
            # survives.
            _remove_invalid_main_snapshots(spec, token=token)
            snapshot_kwargs["force_download"] = True
        elif _cleanup_broken_scoped_snapshot_entries(main_snapshots, spec.allow_patterns):
            snapshot_kwargs["force_download"] = True
    if spec.revision:
        snapshot_kwargs["revision"] = spec.revision
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
    if not _verify_and_record_downloaded_snapshot(spec, resolved, token=token):
        raise RuntimeError(
            f"Downloaded model snapshot is incomplete: {spec.repo_id}"
        )
    downloaded_result: dict[str, object] = {
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
    if spec.revision:
        downloaded_result["revision"] = spec.revision
    return downloaded_result


def download_model_asset(
    spec: ModelAssetSpec,
    *,
    update_task: TaskUpdate,
    token: str = "",
) -> dict[str, object]:
    """Ensure a model asset is cached and return its resolved status.

    Calls targeting the same repository/revision are serialized across UI and
    runtime entry points so validation and cleanup cannot race an in-progress
    snapshot download.
    """

    with _model_asset_download_lock(spec.lock_key):
        return _download_model_asset_unlocked(spec, update_task=update_task, token=token)


__all__ = [
    "ModelAssetSpec",
    "download_model_asset",
    "find_cached_huggingface_snapshot",
    "inspect_model_asset",
]
