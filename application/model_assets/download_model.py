from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

from config.perception import DEFAULT_PERCEPTION_MODEL
from core.model_assets.service import (
    ModelAssetSpec,
    download_model_asset,
    inspect_model_asset,
)
from sdk.path_utils import reject_control_chars

from .registry import (
    ASR_FASTER_WHISPER_ASSET_ID as _ASR_FASTER_WHISPER_ASSET_ID,
    HUGGINGFACE_REPO_ASSET_ID as _HUGGINGFACE_REPO_ASSET_ID,
    MEMORY_EMBEDDING_ASSET_ID as _MEMORY_EMBEDDING_ASSET_ID,
    MODEL_ASSET_REGISTRY,
    MOONDREAM_VISION_ASSET_ID as _MOONDREAM_VISION_ASSET_ID,
    ModelAssetDefinition,
    ModelAssetRegistry,
    PERCEPTION_VLM_ASSET_ID as _PERCEPTION_VLM_ASSET_ID,
    configure_registered_model_assets,
)

_PERCEPTION_ALLOW_PATTERNS = (
    "*.json",
    "*.safetensors",
    "*.txt",
    "*.model",
    "*.tiktoken",
    "*.jinja",
)
_PERCEPTION_REQUIRED_FILE_GROUPS = (
    ("config.json",),
    ("preprocessor_config.json", "processor_config.json"),
    ("tokenizer.json", "tokenizer_config.json"),
    ("model.safetensors", "model-*.safetensors"),
)
PERCEPTION_VLM_MODEL_ASSET = ModelAssetSpec(
    asset_id=_PERCEPTION_VLM_ASSET_ID,
    title=f"Perception VLM ({DEFAULT_PERCEPTION_MODEL})",
    variant=DEFAULT_PERCEPTION_MODEL,
    repo_id=DEFAULT_PERCEPTION_MODEL,
    allow_patterns=_PERCEPTION_ALLOW_PATTERNS,
    required_file_groups=_PERCEPTION_REQUIRED_FILE_GROUPS,
)
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
    """Transport-independent request for a configured, named, or direct Hugging Face model asset."""

    asset_id: str = ""
    configured: bool = False
    variant: str | None = None
    repo_id: str | None = None
    revision: str = ""
    title: str = ""
    allow_patterns: tuple[str, ...] = ()
    required_file_groups: tuple[tuple[str, ...], ...] = ()


def _validated_model_reference(value: str) -> str:
    raw = reject_control_chars(str(value or ""), field="model reference")
    if len(raw) > _MAX_MODEL_REFERENCE_LENGTH:
        raise ValueError("model reference is too long")
    return raw


def _optional_clean_text(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return reject_control_chars(text, field=field)


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


def _load_memory_embedding_spec() -> ModelAssetSpec:
    from ai.memory.config import EMBEDDING_MODEL_ASSET

    return EMBEDDING_MODEL_ASSET


def _load_moondream_spec() -> ModelAssetSpec:
    from ai.vision.moondream_adapter import MOONDREAM_MODEL_ASSET

    return MOONDREAM_MODEL_ASSET


def _register_builtin_definitions(registry: ModelAssetRegistry) -> None:
    registry.register_builtin(
        ModelAssetDefinition(
            asset_id=_MEMORY_EMBEDDING_ASSET_ID,
            static_spec_factory=_load_memory_embedding_spec,
            reject_variant_message="memory embedding model requests do not accept a variant",
        )
    )
    registry.register_builtin(
        ModelAssetDefinition(
            asset_id=_MOONDREAM_VISION_ASSET_ID,
            static_spec_factory=_load_moondream_spec,
            reject_variant_message="Moondream model requests do not accept a variant",
        )
    )
    registry.register_builtin(
        ModelAssetDefinition(
            asset_id=_PERCEPTION_VLM_ASSET_ID,
            default_variant=DEFAULT_PERCEPTION_MODEL,
            default_spec=PERCEPTION_VLM_MODEL_ASSET,
            title_template="Perception VLM ({variant})",
            aliases={DEFAULT_PERCEPTION_MODEL: DEFAULT_PERCEPTION_MODEL},
            allow_patterns=_PERCEPTION_ALLOW_PATTERNS,
            required_file_groups=_PERCEPTION_REQUIRED_FILE_GROUPS,
            allow_configured=True,
            configured_key=_PERCEPTION_VLM_ASSET_ID,
            allow_custom_configured_repo=True,
            allow_configured_local_path=True,
            unsupported_variant_message=lambda variant: (
                f"Unsupported perception model name: {variant}. "
                "Use the default model, save a full Hugging Face repository id, or save a local model directory."
            ),
            unsupported_configured_message=lambda variant: (
                f"Unsupported perception model name: {variant}. "
                "Use a full Hugging Face repository id or a local model directory."
            ),
        )
    )
    registry.register_builtin(
        ModelAssetDefinition(
            asset_id=_ASR_FASTER_WHISPER_ASSET_ID,
            default_variant="small",
            title_template="faster-whisper {variant}",
            aliases=_ASR_MODEL_REPOS,
            allow_patterns=_ASR_ALLOW_PATTERNS,
            required_file_groups=_ASR_REQUIRED_FILE_GROUPS,
            allow_configured=True,
            configured_key=_ASR_FASTER_WHISPER_ASSET_ID,
            allow_custom_configured_repo=True,
            allow_configured_local_path=True,
            unsupported_variant_message=lambda variant: (
                f"Unsupported faster-whisper model name: {variant}. "
                "Use a supported model alias, a full Hugging Face repository id, or a local model directory."
            ),
            unsupported_configured_message=lambda variant: (
                f"Unsupported faster-whisper model name: {variant}. "
                "Use a supported model alias, a full Hugging Face repository id, or a local model directory."
            ),
        )
    )
    registry.register_builtin(
        ModelAssetDefinition(
            asset_id=_HUGGINGFACE_REPO_ASSET_ID,
            allow_direct_repo_in_request=True,
            allow_configured=False,
        )
    )


_register_builtin_definitions(MODEL_ASSET_REGISTRY)


def _resolve_direct_repo_definition(
    definition: ModelAssetDefinition,
    request: ModelAssetRequest,
) -> ModelAssetSpec:
    if request.configured:
        raise ValueError("direct Hugging Face repository requests do not accept configured=True")
    raw_repo = request.repo_id if request.repo_id is not None else request.variant
    if not str(raw_repo or "").strip():
        raise ValueError("repoId is required")
    repo_id = _validated_model_reference(str(raw_repo or "").strip())
    if _looks_like_local_model_reference(repo_id):
        raise ValueError(
            "local model paths are not allowed for direct model downloads; expected Hugging Face 'owner/repo'"
        )
    if not _is_huggingface_repo_id(repo_id):
        raise ValueError(
            f"Invalid Hugging Face repository id: {repo_id}. Expected 'owner/repo'."
        )
    clean_revision = _optional_clean_text(request.revision, field="revision")
    clean_title = _optional_clean_text(request.title, field="title")
    variant_label = f"{repo_id}@{clean_revision}" if clean_revision else repo_id
    return ModelAssetSpec(
        asset_id=definition.asset_id,
        title=clean_title or variant_label,
        variant=variant_label,
        source="huggingface",
        repo_id=repo_id,
        revision=clean_revision,
        allow_patterns=request.allow_patterns or definition.allow_patterns,
        required_file_groups=request.required_file_groups or definition.required_file_groups,
        snapshot_validator=definition.snapshot_validator,
    )


def _resolve_definition(
    definition: ModelAssetDefinition,
    request: ModelAssetRequest,
    *,
    configured_lookup: Mapping[str, str],
) -> ModelAssetSpec:
    if definition.static_spec_factory is not None:
        if request.configured or request.variant is not None or request.repo_id is not None:
            raise ValueError(definition.reject_variant_message)
        return definition.static_spec_factory()

    if definition.allow_direct_repo_in_request:
        return _resolve_direct_repo_definition(definition, request)

    if request.repo_id is not None:
        raise ValueError(
            f"{definition.asset_id} requests do not accept repoId; use assetId='{_HUGGINGFACE_REPO_ASSET_ID}' or omit assetId"
        )

    effective_revision = (
        _optional_clean_text(request.revision, field="revision")
        or definition.revision
    )

    if not request.configured:
        raw_variant = (
            definition.default_variant
            if request.variant is None or not str(request.variant).strip()
            else str(request.variant).strip()
        )
        request_variant = _validated_model_reference(raw_variant)
        if _looks_like_local_model_reference(request_variant):
            raise ValueError("local model paths must be saved before they can be checked")
        if (
            definition.default_spec is not None
            and request_variant == definition.default_variant
            and not request.revision
        ):
            return definition.default_spec
        if request_variant in definition.aliases:
            return ModelAssetSpec(
                asset_id=definition.asset_id,
                title=definition.title_template.format(variant=request_variant),
                variant=request_variant,
                repo_id=definition.aliases[request_variant],
                revision=effective_revision,
                allow_patterns=definition.allow_patterns,
                required_file_groups=definition.required_file_groups,
                snapshot_validator=definition.snapshot_validator,
            )
        if _is_huggingface_repo_id(request_variant):
            raise ValueError(
                "custom Hugging Face model ids must be saved before they can be checked"
            )
        message_builder = definition.unsupported_variant_message
        raise ValueError(
            message_builder(request_variant)
            if message_builder is not None
            else f"Unsupported model variant for {definition.asset_id}: {request_variant}"
        )

    if not definition.allow_configured:
        raise ValueError(definition.reject_variant_message)
    if request.variant is not None:
        raise ValueError("configured model asset requests must not include a variant")

    raw_configured = ""
    if definition.configured_getter is not None:
        raw_configured = str(definition.configured_getter() or "").strip()
    elif definition.configured_key:
        raw_configured = str(configured_lookup.get(definition.configured_key, "") or "").strip()
    variant = _validated_model_reference(raw_configured or definition.default_variant)

    if (
        definition.default_spec is not None
        and variant == definition.default_variant
        and not request.revision
    ):
        return definition.default_spec

    title = definition.title_template.format(variant=variant)
    if variant in definition.aliases:
        return ModelAssetSpec(
            asset_id=definition.asset_id,
            title=title,
            variant=variant,
            repo_id=definition.aliases[variant],
            revision=effective_revision,
            allow_patterns=definition.allow_patterns,
            required_file_groups=definition.required_file_groups,
            snapshot_validator=definition.snapshot_validator,
        )

    local_path: Path | None = None
    if definition.allow_configured_local_path:
        if _looks_like_local_model_reference(variant):
            local_path = _configured_local_model_path(variant)
        else:
            configured_path = _configured_local_model_path(variant)
            if configured_path.exists():
                local_path = configured_path
    if local_path is not None:
        return ModelAssetSpec(
            asset_id=definition.asset_id,
            title=title,
            variant=variant,
            source="local",
            local_path=local_path,
            required_file_groups=definition.required_file_groups,
            snapshot_validator=definition.snapshot_validator,
        )

    if definition.allow_custom_configured_repo and _is_huggingface_repo_id(variant):
        return ModelAssetSpec(
            asset_id=definition.asset_id,
            title=title,
            variant=variant,
            repo_id=variant,
            revision=effective_revision,
            allow_patterns=definition.allow_patterns,
            required_file_groups=definition.required_file_groups,
            snapshot_validator=definition.snapshot_validator,
        )

    configured_error = definition.unsupported_configured_message
    raise ValueError(
        configured_error(variant)
        if configured_error is not None
        else f"Unsupported configured model for {definition.asset_id}: {variant}"
    )


def resolve_model_asset(
    request: ModelAssetRequest,
    *,
    configured_asr_model: str = "small",
    configured_perception_model: str = DEFAULT_PERCEPTION_MODEL,
    configured_values: Mapping[str, str] | None = None,
    registry: ModelAssetRegistry = MODEL_ASSET_REGISTRY,
) -> ModelAssetSpec:
    asset_id = str(request.asset_id or "").strip()
    if not asset_id and request.repo_id is not None:
        asset_id = _HUGGINGFACE_REPO_ASSET_ID

    definition = registry.get(asset_id)
    if definition is None:
        raise ValueError(f"Unsupported model asset: {asset_id or '<empty>'}")

    lookup: dict[str, str] = {
        _ASR_FASTER_WHISPER_ASSET_ID: configured_asr_model,
        _PERCEPTION_VLM_ASSET_ID: configured_perception_model,
    }
    if configured_values:
        lookup.update(configured_values)

    return _resolve_definition(
        definition,
        request,
        configured_lookup=lookup,
    )


def inspect_model(
    request: ModelAssetRequest,
    *,
    configured_asr_model: str = "small",
    configured_perception_model: str = DEFAULT_PERCEPTION_MODEL,
    configured_values: Mapping[str, str] | None = None,
    registry: ModelAssetRegistry = MODEL_ASSET_REGISTRY,
) -> dict[str, object]:
    return inspect_model_asset(
        resolve_model_asset(
            request,
            configured_asr_model=configured_asr_model,
            configured_perception_model=configured_perception_model,
            configured_values=configured_values,
            registry=registry,
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


def create_plugin_model_assets_dispatcher(
    *,
    get_token: Callable[[], str] | None = None,
    get_configured_values: Callable[[], Mapping[str, str]] | None = None,
    registry: ModelAssetRegistry = MODEL_ASSET_REGISTRY,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a host runtime dispatcher for ``sdk.model_assets`` plugin calls."""

    def dispatch(command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("action") or "").strip()
        raw_repo = str(command.get("repoId") or "").strip()
        raw_asset = str(command.get("assetId") or "").strip()
        request = ModelAssetRequest(
            asset_id=raw_asset,
            configured=bool(command.get("configured", False)),
            variant=command.get("variant"),
            repo_id=raw_repo if raw_repo else None,
            revision=str(command.get("revision") or "").strip(),
            title=str(command.get("title") or "").strip(),
            allow_patterns=tuple(command.get("allowPatterns") or ()),
            required_file_groups=tuple(
                tuple(group) for group in (command.get("requiredFileGroups") or ())
            ),
        )
        configured_map = dict(get_configured_values() or {}) if get_configured_values else {}
        if action == "status":
            return dict(
                inspect_model(
                    request,
                    configured_values=configured_map,
                    registry=registry,
                )
            )
        if action == "download":
            spec = resolve_model_asset(
                request,
                configured_values=configured_map,
                registry=registry,
            )
            on_progress = command.get("onProgress")
            progress_cb = on_progress if callable(on_progress) else (lambda **_changes: None)
            token = str(get_token() or "").strip() if get_token is not None else ""
            return dict(
                download_model(
                    spec,
                    update_task=progress_cb,
                    token=token,
                )
            )
        raise ValueError(f"Unsupported plugin model-assets action: {action or '<empty>'}")

    return dispatch


__all__ = [
    "MODEL_ASSET_REGISTRY",
    "ModelAssetDefinition",
    "ModelAssetRegistry",
    "ModelAssetRequest",
    "PERCEPTION_VLM_MODEL_ASSET",
    "configure_registered_model_assets",
    "create_plugin_model_assets_dispatcher",
    "download_model",
    "inspect_model",
    "resolve_model_asset",
]
