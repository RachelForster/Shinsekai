"""Selected sound-effect projection for chat prompts and runtime playback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.media.effect_audio import parse_effect_audio_bindings
from i18n import tr as tr_i18n


@dataclass(frozen=True)
class SelectedEffectContext:
    """One normalized view of the effects selected for a chat session."""

    selected_names: tuple[str, ...]
    labels: tuple[str, ...]
    keyword_map: dict[str, str]
    prompt_catalog: str

    def append_prompt_catalog(self, system_template: str) -> str:
        template = str(system_template or "").rstrip()
        if not self.prompt_catalog:
            return template
        return (
            f"{template}\n\n{self.prompt_catalog}" if template else self.prompt_catalog
        )


def _selected_name_keys(selected_names: Any) -> set[str]:
    if isinstance(selected_names, str):
        values = selected_names.split(",")
    elif isinstance(selected_names, (list, tuple, set, frozenset)):
        values = selected_names
    else:
        values = []
    return {value.casefold() for item in values if (value := str(item or "").strip())}


def build_selected_effect_context(
    config_manager: Any,
    selected_names: Any,
) -> SelectedEffectContext:
    """Build the sole normalized effect view used by prompt and runtime paths.

    ``audio_tags`` and ``audio_list`` are line/index aligned. Empty tag lines are
    deliberately retained so a later label cannot move onto an earlier audio file.
    """

    selected_keys = _selected_name_keys(selected_names)
    if not selected_keys or config_manager is None:
        return SelectedEffectContext((), (), {}, "")

    canonical_names: list[str] = []
    labels: list[str] = []
    seen_labels: set[str] = set()
    keyword_map: dict[str, str] = {}
    effects = getattr(getattr(config_manager, "config", None), "effect_list", []) or []

    for effect in effects:
        effect_name = str(getattr(effect, "name", "") or "").strip()
        if not effect_name or effect_name.casefold() not in selected_keys:
            continue
        canonical_names.append(effect_name)

        bindings = parse_effect_audio_bindings(
            getattr(effect, "audio_tags", ""),
            getattr(effect, "audio_list", []) or [],
        )
        for binding in bindings:
            keyword_map[binding.keyword] = binding.audio_path
            label_key = binding.keyword.casefold()
            if label_key not in seen_labels:
                seen_labels.add(label_key)
                labels.append(binding.keyword)

    prompt_catalog = ""
    if labels:
        header = tr_i18n("template_gen.effects_header").strip()
        prompt_catalog = "\n".join([header, *(f"- {label}" for label in labels)])

    return SelectedEffectContext(
        selected_names=tuple(canonical_names),
        labels=tuple(labels),
        keyword_map=keyword_map,
        prompt_catalog=prompt_catalog,
    )
