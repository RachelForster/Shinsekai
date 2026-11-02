"""Selected effect resources for chat prompts and runtime playback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from core.media.effect_bindings import effect_modes, parse_effect_bindings
from core.media.effect_image import ImageEffectAsset


@dataclass(frozen=True)
class EffectCatalogItem:
    label: str
    kind: str
    modes: tuple[str, ...]


@dataclass(frozen=True)
class SelectedEffectContext:
    """One normalized view of the effects selected for a chat session."""

    selected_names: tuple[str, ...]
    labels: tuple[str, ...]
    keyword_map: dict[str, str]
    image_keyword_map: dict[str, ImageEffectAsset] = field(default_factory=dict)

    @property
    def catalog(self) -> tuple[EffectCatalogItem, ...]:
        """Describe each advertised alias using the final playback bindings."""
        items: list[EffectCatalogItem] = []
        for label in self.labels:
            key = label.casefold()
            image = self.image_keyword_map.get(key)
            has_audio = bool((image and image.audio_path) or self.keyword_map.get(key))
            if image is not None:
                kind = "image_audio" if has_audio else "image"
            else:
                kind = "audio"
            items.append(
                EffectCatalogItem(
                    label, kind, effect_modes(has_image=image is not None)
                )
            )
        return tuple(items)


class EffectConfigReader(Protocol):
    """Narrow configuration dependency required by the chat effect action."""

    def list_effects(self) -> Sequence[Any]: ...


def _selected_name_keys(selected_names: Any) -> set[str]:
    if isinstance(selected_names, str):
        values = selected_names.split(",")
    elif isinstance(selected_names, (list, tuple, set, frozenset)):
        values = selected_names
    else:
        values = []
    return {value.casefold() for item in values if (value := str(item or "").strip())}


def build_effect_context(
    config_reader: EffectConfigReader | None,
    selected_names: Any,
) -> SelectedEffectContext:
    """Build the sole normalized effect view used by prompt and runtime paths.

    ``audio_tags`` and ``audio_list`` are line/index aligned. Empty tag lines are
    deliberately retained so a later label cannot move onto an earlier audio file.
    """

    selected_keys = _selected_name_keys(selected_names)
    if not selected_keys or config_reader is None:
        return SelectedEffectContext((), (), {})

    canonical_names: list[str] = []
    labels: list[str] = []
    seen_labels: set[str] = set()
    keyword_map: dict[str, str] = {}
    image_keyword_map: dict[str, ImageEffectAsset] = {}
    effects = config_reader.list_effects()

    for effect in effects:
        effect_name = str(getattr(effect, "name", "") or "").strip()
        if not effect_name or effect_name.casefold() not in selected_keys:
            continue
        canonical_names.append(effect_name)

        bindings = parse_effect_bindings(
            getattr(effect, "audio_tags", ""),
            getattr(effect, "audio_list", []) or [],
        )
        for binding in bindings:
            keyword_map[binding.keyword.casefold()] = binding.path
            label = binding.source_label or binding.keyword
            keyword_map[label.casefold()] = binding.path
            label_key = binding.keyword.casefold()
            if label_key not in seen_labels:
                seen_labels.add(label_key)
                labels.append(binding.keyword)

        images = getattr(effect, "image_list", []) or []
        image_audio = getattr(effect, "image_audio_list", []) or []
        for binding in parse_effect_bindings(
            getattr(effect, "image_tags", ""), images
        ):
            index = binding.index
            asset = ImageEffectAsset(
                image_path=binding.path,
                audio_path=(
                    str(image_audio[index] or "") if index < len(image_audio) else ""
                ),
            )
            label = binding.source_label or binding.keyword
            # Later resources win as a whole, including an absent bound audio.
            image_keyword_map[binding.keyword.casefold()] = asset
            image_keyword_map[label.casefold()] = asset
            label_key = binding.keyword.casefold()
            if label_key not in seen_labels:
                seen_labels.add(label_key)
                labels.append(binding.keyword)

    return SelectedEffectContext(
        selected_names=tuple(canonical_names),
        labels=tuple(labels),
        keyword_map=keyword_map,
        image_keyword_map=image_keyword_map,
    )
