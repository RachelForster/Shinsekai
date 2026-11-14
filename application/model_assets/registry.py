"""Declarative registry for host and plugin-contributed model assets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import threading

from core.model_assets.service import ModelAssetSpec
from sdk.model_assets import (
    ModelAssetContribution,
    RESERVED_HOST_MODEL_ASSET_IDS,
)

HUGGINGFACE_REPO_ASSET_ID = "huggingface.repo"
ASR_FASTER_WHISPER_ASSET_ID = "asr.faster-whisper"
MEMORY_EMBEDDING_ASSET_ID = "memory.embedding"
MOONDREAM_VISION_ASSET_ID = "vision.moondream"
PERCEPTION_VLM_ASSET_ID = "perception.vlm"


@dataclass(frozen=True, slots=True)
class ModelAssetDefinition:
    """Declarative rule set describing how an ``asset_id`` resolves to ``ModelAssetSpec``."""

    asset_id: str
    static_spec_factory: Callable[[], ModelAssetSpec] | None = None
    reject_variant_message: str = "model requests do not accept a variant"
    default_variant: str = ""
    default_spec: ModelAssetSpec | None = None
    title_template: str = "{variant}"
    aliases: Mapping[str, str] = field(default_factory=dict)
    revision: str = ""
    allow_patterns: tuple[str, ...] = ()
    required_file_groups: tuple[tuple[str, ...], ...] = ()
    snapshot_validator: Callable[[Path], bool] | None = None
    enforce_allow_patterns: bool = True
    allow_direct_repo_in_request: bool = False
    allow_configured: bool = False
    configured_key: str = ""
    configured_getter: Callable[[], str] | None = None
    allow_custom_configured_repo: bool = True
    allow_configured_local_path: bool = False
    unsupported_variant_message: Callable[[str], str] | None = None
    unsupported_configured_message: Callable[[str], str] | None = None
    plugin_id: str = ""


class ModelAssetRegistry:
    """Thread-safe registry of built-in and plugin-contributed model asset definitions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._builtins: dict[str, ModelAssetDefinition] = {}
        self._plugins: dict[str, ModelAssetDefinition] = {}

    def register_builtin(self, definition: ModelAssetDefinition) -> None:
        asset_id = str(definition.asset_id or "").strip()
        if not asset_id:
            raise ValueError("ModelAssetDefinition.asset_id is required")
        with self._lock:
            self._builtins[asset_id] = definition

    def register_plugin_definition(self, definition: ModelAssetDefinition) -> None:
        asset_id = str(definition.asset_id or "").strip()
        if not asset_id:
            raise ValueError("ModelAssetDefinition.asset_id is required")
        if asset_id in RESERVED_HOST_MODEL_ASSET_IDS or asset_id in self._builtins:
            raise ValueError(f"'{asset_id}' is a reserved host model asset id")
        with self._lock:
            self._plugins[asset_id] = definition

    def configure_plugin_contributions(
        self,
        contributions: Iterable[ModelAssetContribution],
    ) -> None:
        next_plugins: dict[str, ModelAssetDefinition] = {}
        for contribution in contributions:
            definition = definition_from_plugin_contribution(contribution)
            if (
                definition.asset_id in RESERVED_HOST_MODEL_ASSET_IDS
                or definition.asset_id in self._builtins
            ):
                raise ValueError(
                    f"'{definition.asset_id}' is a reserved host model asset id"
                )
            if definition.asset_id in next_plugins:
                raise ValueError(f"duplicate plugin model asset: {definition.asset_id}")
            next_plugins[definition.asset_id] = definition
        with self._lock:
            self._plugins = next_plugins

    def clear_plugin_contributions(self) -> None:
        with self._lock:
            self._plugins.clear()

    def get(self, asset_id: str) -> ModelAssetDefinition | None:
        key = str(asset_id or "").strip()
        if not key:
            return None
        with self._lock:
            return self._builtins.get(key) or self._plugins.get(key)

    def list_definitions(self) -> tuple[ModelAssetDefinition, ...]:
        with self._lock:
            merged = {**self._plugins, **self._builtins}
            return tuple(merged[key] for key in sorted(merged))


def definition_from_plugin_contribution(
    contribution: ModelAssetContribution,
) -> ModelAssetDefinition:
    """Project a plugin SDK ``ModelAssetContribution`` into a host ``ModelAssetDefinition``."""
    aliases = dict(contribution.aliases)
    default_variant = contribution.repo_id
    if default_variant and default_variant not in aliases:
        aliases[default_variant] = contribution.repo_id
    elif not default_variant and aliases:
        default_variant = next(iter(aliases))

    fixed_title = contribution.title.strip()
    title_template = fixed_title if fixed_title and "{variant}" in fixed_title else (
        f"{fixed_title} ({{variant}})"
        if fixed_title and len(aliases) > 1
        else (fixed_title or f"{contribution.asset_id} ({{variant}})")
    )

    is_static_only = (
        bool(contribution.repo_id)
        and not contribution.aliases
        and contribution.configured_model_getter is None
    )
    if is_static_only:
        spec = ModelAssetSpec(
            asset_id=contribution.asset_id,
            title=fixed_title or contribution.repo_id,
            variant=contribution.repo_id,
            repo_id=contribution.repo_id,
            revision=contribution.revision,
            allow_patterns=contribution.allow_patterns,
            required_file_groups=contribution.required_file_groups,
            snapshot_validator=contribution.snapshot_validator,
        )
        return ModelAssetDefinition(
            asset_id=contribution.asset_id,
            static_spec_factory=lambda spec=spec: spec,
            reject_variant_message=(
                f"{contribution.asset_id} model requests do not accept a variant"
            ),
            plugin_id=contribution.plugin_id,
        )

    return ModelAssetDefinition(
        asset_id=contribution.asset_id,
        default_variant=default_variant,
        title_template=title_template,
        aliases=aliases,
        revision=contribution.revision,
        allow_patterns=contribution.allow_patterns,
        required_file_groups=contribution.required_file_groups,
        snapshot_validator=contribution.snapshot_validator,
        allow_configured=contribution.configured_model_getter is not None,
        configured_getter=contribution.configured_model_getter,
        allow_custom_configured_repo=contribution.allow_custom_configured_repo,
        allow_configured_local_path=contribution.allow_configured_local_path,
        unsupported_variant_message=lambda v, aid=contribution.asset_id: (
            f"Unsupported model variant for {aid}: {v}."
        ),
        unsupported_configured_message=lambda v, aid=contribution.asset_id: (
            f"Unsupported configured model for {aid}: {v}."
        ),
        plugin_id=contribution.plugin_id,
    )


MODEL_ASSET_REGISTRY = ModelAssetRegistry()


def configure_registered_model_assets(
    contributions: Iterable[ModelAssetContribution],
) -> None:
    """Replace plugin-contributed model asset definitions in the shared registry."""
    MODEL_ASSET_REGISTRY.configure_plugin_contributions(contributions)


__all__ = [
    "ASR_FASTER_WHISPER_ASSET_ID",
    "HUGGINGFACE_REPO_ASSET_ID",
    "MEMORY_EMBEDDING_ASSET_ID",
    "MODEL_ASSET_REGISTRY",
    "MOONDREAM_VISION_ASSET_ID",
    "ModelAssetDefinition",
    "ModelAssetRegistry",
    "PERCEPTION_VLM_ASSET_ID",
    "configure_registered_model_assets",
    "definition_from_plugin_contribution",
]
