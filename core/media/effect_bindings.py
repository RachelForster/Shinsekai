"""Framework-neutral parsing for effect resource keyword bindings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import re

from core.media.asset_tags import tag_contents


_KEYWORD_SEPARATOR_RE = re.compile(r"[,，]")


@dataclass(frozen=True, slots=True)
class EffectBinding:
    keyword: str
    path: str
    source_label: str = field(default="", compare=False)
    index: int = field(default=0, compare=False)


def parse_effect_bindings(
    tags: object,
    paths: Sequence[object] | None,
) -> tuple[EffectBinding, ...]:
    """Pair configured resource paths with comma-separated trigger keywords.

    Blank tag lines retain their index so each line stays aligned with the
    corresponding resource path.
    """

    paths = tuple(paths or ())
    bindings: list[EffectBinding] = []
    for index, keyword_block in enumerate(
        tag_contents(str(tags or ""), len(paths), preserve_blank_lines=True)
    ):
        if not keyword_block or not paths[index]:
            continue
        path = str(paths[index])
        seen_keywords: set[str] = set()
        for part in _KEYWORD_SEPARATOR_RE.split(keyword_block):
            keyword = part.strip()
            key = keyword.casefold()
            if not keyword or key in seen_keywords:
                continue
            seen_keywords.add(key)
            bindings.append(
                EffectBinding(
                    keyword=keyword,
                    path=path,
                    source_label=keyword_block,
                    index=index,
                )
            )
    return tuple(bindings)


def effect_modes(*, has_image: bool) -> tuple[str, ...]:
    """Images are one-shot presentations; only audio supports looping."""
    return ("before", "after") if has_image else ("before", "after", "loop", "stop")
