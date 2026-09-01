from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.model_assets.service import (
    ModelAssetSpec,
    download_model_asset,
    inspect_model_asset,
)

from sdk.path_utils import reject_control_chars

_ASR_FASTER_WHISPER_ASSET_ID = "asr.faster-whisper"
_MEMORY_EMBEDDING_ASSET_ID = "memory.embedding"
_ASR_ALLOW_PATTERNS = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)
_ASR_REQUIRED_FILE_GROUPS = (
    ("config.json",),
    ("model.bin",),
    ("tokenizer.json",),
)
_ASR_MODEL_REPOS = {
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "tiny": "Systran/faster-whisper-tiny",
    "base.en": "Systran/faster-whisper-base.en",
    "base": "Systran/faster-whisper-base",
    "small.en": "Systran/faster-whisper-small.en",
    "small": "Systran/faster-whisper-small",
    "medium.en": "Systran/faster-whisper-medium.en",
    "medium": "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large": "Systran/faster-whisper-large-v3",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
_HF_REPO_COMPONENT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?$")
_WINDOWS_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:(?:$|[^\\/])")
_WINDOWS_RESERVED_DEVICE_RE = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])$",
    re.IGNORECASE,
)
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_MAX_MODEL_REFERENCE_LENGTH = 512


@dataclass(frozen=True, slots=True)
class ModelAssetRequest:
    """Transport-independent request for a configured or named model asset."""

    asset_id: str
    configured: bool = False
    variant: str | None = None


def _validated_model_reference(value: str) -> str:
    raw = reject_control_chars(str(value or ""), field="model reference")
    if len(raw) > _MAX_MODEL_REFERENCE_LENGTH:
        raise ValueError("model reference is too long")
    return raw


def _is_huggingface_repo_id(value: str) -> bool:
    if len(value) > 96 or value.count("/") != 1:
        return False
    owner, model = value.split("/", 1)
    return bool(
        _HF_REPO_COMPONENT_RE.fullmatch(owner)
        and _HF_REPO_COMPONENT_RE.fullmatch(model)
        and "--" not in owner
        and "--" not in model
        and ".." not in owner
        and ".." not in model
    )


def _looks_like_local_model_reference(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return bool(
        value.startswith((".", "/", "\\", "~"))
        or value.endswith(("/", "\\"))
        or "\\" in value
        or _WINDOWS_DRIVE_ABSOLUTE_RE.match(value)
        or normalized.count("/") > 1
    )


def _configured_local_model_path(value: str) -> Path:
    raw = _validated_model_reference(value)
    normalized = raw.replace("\\", "/")
    if _URI_SCHEME_RE.match(raw):
        raise ValueError("model paths must not use URI schemes")
    if os.name == "nt":
        if normalized.startswith("//") or normalized.startswith("/??/"):
            raise ValueError("network and device model paths are not allowed")
        if raw.startswith(("/", "\\")):
            raise ValueError("drive-rooted model paths must include a drive letter")
        if _WINDOWS_DRIVE_RELATIVE_RE.match(raw):
            raise ValueError("drive-relative model paths are not allowed")
        drive_absolute = bool(_WINDOWS_DRIVE_ABSOLUTE_RE.match(raw))
        if ":" in raw and (not drive_absolute or ":" in raw[2:]):
            raise ValueError("model path contains an unsupported colon")

    component_separator = r"[\\/]+" if os.name == "nt" else r"/+"
    for component in re.split(component_separator, raw):
        if component in {"", "."}:
            continue
        if component == "..":
            raise ValueError("model path traversal is not allowed")
        if os.name == "nt":
            if component.endswith((" ", ".")):
                raise ValueError(
                    "model path components must not end with spaces or dots"
                )
            device_name = component.split(".", 1)[0].rstrip(" .")
            if _WINDOWS_RESERVED_DEVICE_RE.fullmatch(device_name):
                raise ValueError("Windows device names are not allowed in model paths")

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)

    root = Path.cwd().resolve(strict=False)
    resolved = (root / candidate).resolve(strict=False)
    try:
        within_root = os.path.commonpath([str(root), str(resolved)]) == str(root)
    except ValueError:
        within_root = False
    if not within_root:
        raise PermissionError("relative model path is outside the project root")
    return resolved


def _faster_whisper_repo_id(model_name: str) -> str:
    model = _validated_model_reference(str(model_name or "small").strip() or "small")
    if model in _ASR_MODEL_REPOS:
        return _ASR_MODEL_REPOS[model]
    if _is_huggingface_repo_id(model):
        return model
    raise ValueError(
        f"Unsupported faster-whisper model name: {model}. "
        "Use a supported model alias, a full Hugging Face repository id, or a local model directory."
    )


def resolve_model_asset(
    request: ModelAssetRequest,
    *,
    configured_asr_model: str = "small",
) -> ModelAssetSpec:
    asset_id = str(request.asset_id or "").strip()
    if asset_id == _MEMORY_EMBEDDING_ASSET_ID:
        if request.configured or request.variant is not None:
            raise ValueError("memory embedding model requests do not accept a variant")
        from ai.memory.config import EMBEDDING_MODEL_ASSET

        return EMBEDDING_MODEL_ASSET
    if asset_id != _ASR_FASTER_WHISPER_ASSET_ID:
        raise ValueError(f"Unsupported model asset: {asset_id or '<empty>'}")

    # Security boundary: request variants are network identifiers only. Local
    # filesystem paths may come only from the persisted server-side config.
    if not request.configured:
        request_variant = _validated_model_reference(str(request.variant or "small"))
        if _looks_like_local_model_reference(request_variant):
            raise ValueError(
                "local model paths must be saved before they can be checked"
            )
        if request_variant not in _ASR_MODEL_REPOS:
            if _is_huggingface_repo_id(request_variant):
                raise ValueError(
                    "custom Hugging Face model ids must be saved before they can be checked"
                )
            _faster_whisper_repo_id(
                request_variant
            )  # Raises the canonical unsupported-model error.
        return ModelAssetSpec(
            asset_id=asset_id,
            title=f"faster-whisper {request_variant}",
            variant=request_variant,
            repo_id=_ASR_MODEL_REPOS[request_variant],
            allow_patterns=_ASR_ALLOW_PATTERNS,
            required_file_groups=_ASR_REQUIRED_FILE_GROUPS,
        )

    if request.variant is not None:
        raise ValueError("configured model asset requests must not include a variant")
    variant = _validated_model_reference(configured_asr_model)

    title = f"faster-whisper {variant}"
    local_path: Path | None = None
    if _looks_like_local_model_reference(variant):
        local_path = _configured_local_model_path(variant)
    elif variant not in _ASR_MODEL_REPOS:
        # Preserve legacy relative local model configs without letting an HTTP
        # request value reach the filesystem. Explicit aliases always remain
        # Hugging Face models; ambiguous custom values are local only when the
        # validated configured path already exists.
        configured_path = _configured_local_model_path(variant)
        if configured_path.exists():
            local_path = configured_path
    if local_path is not None:
        return ModelAssetSpec(
            asset_id=asset_id,
            title=title,
            variant=variant,
            source="local",
            local_path=local_path,
            required_file_groups=_ASR_REQUIRED_FILE_GROUPS,
        )
    return ModelAssetSpec(
        asset_id=asset_id,
        title=title,
        variant=variant,
        repo_id=_faster_whisper_repo_id(variant),
        allow_patterns=_ASR_ALLOW_PATTERNS,
        required_file_groups=_ASR_REQUIRED_FILE_GROUPS,
    )


def inspect_model(
    request: ModelAssetRequest,
    *,
    configured_asr_model: str = "small",
) -> dict[str, object]:
    return inspect_model_asset(
        resolve_model_asset(
            request,
            configured_asr_model=configured_asr_model,
        )
    )


def download_model(
    spec: ModelAssetSpec,
    *,
    update_task: Callable[..., None],
    token: str = "",
) -> dict[str, object]:
    """Download one resolved model while reporting progress through a callback."""

    return download_model_asset(
        spec,
        update_task=update_task,
        token=str(token or "").strip(),
    )
