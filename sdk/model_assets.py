"""Plugin-scoped model asset registration, inspection, and Hugging Face downloads."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any

from sdk.frontend_ui import _clean_identifier
from sdk.path_utils import reject_control_chars

__all__ = [
    "ModelAssetContribution",
    "ModelAssetsController",
    "RESERVED_HOST_MODEL_ASSET_IDS",
    "download_huggingface_model",
    "download_registered_model_asset",
    "inspect_huggingface_model",
    "inspect_registered_model_asset",
]

RESERVED_HOST_MODEL_ASSET_IDS: frozenset[str] = frozenset(
    {
        "asr.faster-whisper",
        "huggingface.repo",
        "memory.embedding",
        "perception.vlm",
        "vision.moondream",
    }
)

_MAX_ASSET_ID_LENGTH = 128
_dispatcher_lock = threading.RLock()
_runtime_dispatcher: Callable[[dict[str, Any]], dict[str, Any]] | None = None
_controller_token = object()


def _optional_clean_text(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return reject_control_chars(text, field=field)


def _normalize_asset_id(asset_id: str, *, allow_reserved: bool = False) -> str:
    raw = str(asset_id or "").strip()
    if not raw:
        raise ValueError("model asset_id cannot be empty")
    cleaned = reject_control_chars(raw, field="asset_id")
    if len(cleaned) > _MAX_ASSET_ID_LENGTH:
        raise ValueError(f"model asset_id cannot exceed {_MAX_ASSET_ID_LENGTH} characters")
    if not allow_reserved and cleaned in RESERVED_HOST_MODEL_ASSET_IDS:
        raise ValueError(f"'{cleaned}' is a reserved host model asset id")
    return cleaned


def _normalize_patterns(patterns: Sequence[str] | None) -> tuple[str, ...]:
    if not patterns:
        return ()
    return tuple(
        reject_control_chars(str(item).strip(), field="allow_pattern")
        for item in patterns
        if str(item).strip()
    )


def _normalize_file_groups(
    groups: Sequence[Sequence[str]] | None,
) -> tuple[tuple[str, ...], ...]:
    if not groups:
        return ()
    normalized: list[tuple[str, ...]] = []
    for group in groups:
        if isinstance(group, (str, bytes)):
            raise TypeError("each required_file_groups entry must be a sequence of patterns")
        cleaned_group = _normalize_patterns(group)
        if cleaned_group:
            normalized.append(cleaned_group)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ModelAssetContribution:
    """Declarative model asset registered by a plugin during ``initialize``."""

    asset_id: str
    repo_id: str = ""
    title: str = ""
    revision: str = ""
    allow_patterns: tuple[str, ...] = ()
    required_file_groups: tuple[tuple[str, ...], ...] = ()
    aliases: Mapping[str, str] = field(default_factory=dict)
    configured_model_getter: Callable[[], str] | None = None
    allow_custom_configured_repo: bool = True
    allow_configured_local_path: bool = False
    snapshot_validator: Callable[[Path], bool] | None = None
    plugin_id: str = ""

    def __post_init__(self) -> None:
        cleaned_id = _normalize_asset_id(self.asset_id, allow_reserved=False)
        cleaned_repo = _optional_clean_text(self.repo_id, field="repo_id")
        cleaned_title = _optional_clean_text(self.title, field="title")
        cleaned_rev = _optional_clean_text(self.revision, field="revision")
        cleaned_aliases = {
            reject_control_chars(str(k).strip(), field="alias"): reject_control_chars(
                str(v).strip(), field="alias repo_id"
            )
            for k, v in dict(self.aliases or {}).items()
            if str(k).strip() and str(v).strip()
        }
        if not cleaned_repo and not cleaned_aliases and self.configured_model_getter is None:
            raise ValueError(
                "ModelAssetContribution requires repo_id, aliases, or configured_model_getter"
            )
        if self.configured_model_getter is not None and not callable(
            self.configured_model_getter
        ):
            raise TypeError("configured_model_getter must be callable")
        if self.snapshot_validator is not None and not callable(self.snapshot_validator):
            raise TypeError("snapshot_validator must be callable")
        object.__setattr__(self, "asset_id", cleaned_id)
        object.__setattr__(self, "repo_id", cleaned_repo)
        object.__setattr__(self, "title", cleaned_title)
        object.__setattr__(self, "revision", cleaned_rev)
        object.__setattr__(self, "allow_patterns", _normalize_patterns(self.allow_patterns))
        object.__setattr__(
            self,
            "required_file_groups",
            _normalize_file_groups(self.required_file_groups),
        )
        object.__setattr__(self, "aliases", cleaned_aliases)


def _bind_model_assets_dispatcher(
    dispatcher: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> None:
    """Host-only: bind plugin model-asset status/download operations to the host service."""
    global _runtime_dispatcher
    with _dispatcher_lock:
        _runtime_dispatcher = dispatcher


def _dispatch_model_asset_command(command: dict[str, Any]) -> dict[str, Any]:
    with _dispatcher_lock:
        dispatcher = _runtime_dispatcher
    if dispatcher is None:
        raise RuntimeError(
            "Model assets runtime is not bound in this process; ensure host model-asset bindings are initialized"
        )
    return dict(dispatcher(command))


def _controller_for_plugin(plugin_id: str) -> "ModelAssetsController":
    return ModelAssetsController(
        _clean_identifier(plugin_id, label="plugin_id"),
        _token=_controller_token,
    )


class ModelAssetsController:
    """Inspect and download Hugging Face or registered model assets from a plugin."""

    __slots__ = ("_plugin_id",)

    def __init__(self, plugin_id: str, *, _token: object | None = None) -> None:
        if _token is not _controller_token:
            raise TypeError(
                "ModelAssetsController instances must be created by register.model_assets()"
            )
        self._plugin_id = plugin_id

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    def status(
        self,
        repo_id: str = "",
        *,
        asset_id: str = "",
        variant: str | None = None,
        configured: bool = False,
        revision: str = "",
    ) -> dict[str, Any]:
        """Inspect cache status for a direct Hugging Face ``repo_id`` or registered ``asset_id``."""
        clean_repo = str(repo_id or "").strip()
        clean_asset = str(asset_id or "").strip()
        if not clean_repo and not clean_asset:
            raise ValueError("status() requires either repo_id or asset_id")
        return _dispatch_model_asset_command(
            {
                "action": "status",
                "pluginId": self._plugin_id,
                "repoId": clean_repo,
                "assetId": clean_asset,
                "variant": variant,
                "configured": bool(configured),
                "revision": str(revision or "").strip(),
            }
        )

    def download(
        self,
        repo_id: str = "",
        *,
        asset_id: str = "",
        variant: str | None = None,
        configured: bool = False,
        revision: str = "",
        title: str = "",
        allow_patterns: Sequence[str] = (),
        required_file_groups: Sequence[Sequence[str]] = (),
        on_progress: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        """Download a direct Hugging Face ``repo_id`` (full snapshot by default) or registered ``asset_id``."""
        clean_repo = str(repo_id or "").strip()
        clean_asset = str(asset_id or "").strip()
        if not clean_repo and not clean_asset:
            raise ValueError("download() requires either repo_id or asset_id")
        if clean_asset and (allow_patterns or required_file_groups):
            raise ValueError(
                "allow_patterns and required_file_groups overrides are only supported for direct repo_id downloads"
            )
        return _dispatch_model_asset_command(
            {
                "action": "download",
                "pluginId": self._plugin_id,
                "repoId": clean_repo,
                "assetId": clean_asset,
                "variant": variant,
                "configured": bool(configured),
                "revision": str(revision or "").strip(),
                "title": str(title or "").strip(),
                "allowPatterns": _normalize_patterns(allow_patterns),
                "requiredFileGroups": _normalize_file_groups(required_file_groups),
                "onProgress": on_progress,
            }
        )


def inspect_huggingface_model(
    repo_id: str,
    *,
    revision: str = "",
) -> dict[str, Any]:
    """Inspect whether ``owner/repo`` is cached in the host Hugging Face hub cache."""
    clean_repo = str(repo_id or "").strip()
    if not clean_repo:
        raise ValueError("repo_id cannot be empty")
    return _dispatch_model_asset_command(
        {
            "action": "status",
            "repoId": clean_repo,
            "revision": str(revision or "").strip(),
        }
    )


def download_huggingface_model(
    repo_id: str,
    *,
    revision: str = "",
    title: str = "",
    allow_patterns: Sequence[str] = (),
    required_file_groups: Sequence[Sequence[str]] = (),
    on_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Download ``owner/repo`` into the host Hugging Face cache using the host token & locks."""
    clean_repo = str(repo_id or "").strip()
    if not clean_repo:
        raise ValueError("repo_id cannot be empty")
    return _dispatch_model_asset_command(
        {
            "action": "download",
            "repoId": clean_repo,
            "revision": str(revision or "").strip(),
            "title": str(title or "").strip(),
            "allowPatterns": _normalize_patterns(allow_patterns),
            "requiredFileGroups": _normalize_file_groups(required_file_groups),
            "onProgress": on_progress,
        }
    )


def inspect_registered_model_asset(
    asset_id: str,
    *,
    variant: str | None = None,
    configured: bool = False,
) -> dict[str, Any]:
    """Inspect cache status of a registered host or plugin model asset."""
    clean_asset = str(asset_id or "").strip()
    if not clean_asset:
        raise ValueError("asset_id cannot be empty")
    return _dispatch_model_asset_command(
        {
            "action": "status",
            "assetId": clean_asset,
            "variant": variant,
            "configured": bool(configured),
        }
    )


def download_registered_model_asset(
    asset_id: str,
    *,
    variant: str | None = None,
    configured: bool = False,
    on_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Download a registered host or plugin model asset using the host token & locks."""
    clean_asset = str(asset_id or "").strip()
    if not clean_asset:
        raise ValueError("asset_id cannot be empty")
    return _dispatch_model_asset_command(
        {
            "action": "download",
            "assetId": clean_asset,
            "variant": variant,
            "configured": bool(configured),
            "onProgress": on_progress,
        }
    )
