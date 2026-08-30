"""Selected sound-effect projection for chat prompts and runtime playback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from i18n import tr as tr_i18n


_LABEL_SEPARATOR_RE = re.compile(r"[,，]")


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


def _effect_labels(tag_line: Any) -> tuple[str, ...]:
    raw = str(tag_line or "").strip()
    if not raw:
        return ()
    if "：" in raw:
        raw = raw.split("：", 1)[-1]
    elif ":" in raw:
        raw = raw.split(":", 1)[-1]

    labels: list[str] = []
    seen: set[str] = set()
    for part in _LABEL_SEPARATOR_RE.split(raw):
        label = part.strip()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            labels.append(label)
    return tuple(labels)


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

        tag_lines = str(getattr(effect, "audio_tags", "") or "").splitlines()
        audio_list = getattr(effect, "audio_list", []) or []
        for index, audio_path in enumerate(audio_list):
            path = str(audio_path or "").strip()
            tag_line = tag_lines[index] if index < len(tag_lines) else ""
            if not path:
                continue
            for label in _effect_labels(tag_line):
                keyword_map[label] = path
                label_key = label.casefold()
                if label_key not in seen_labels:
                    seen_labels.add(label_key)
                    labels.append(label)

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
