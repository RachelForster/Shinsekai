"""Framework-neutral parsing for effect-audio keyword bindings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re


_KEYWORD_SEPARATOR_RE = re.compile(r"[,，]")


@dataclass(frozen=True, slots=True)
class EffectAudioBinding:
    keyword: str
    audio_path: str


def parse_effect_audio_bindings(
    audio_tags: object,
    audio_paths: Sequence[object] | None,
) -> tuple[EffectAudioBinding, ...]:
    """Pair configured audio paths with comma-separated trigger keywords.

    Blank tag lines retain their index so each line stays aligned with the
    corresponding audio path.
    """

    paths = tuple(audio_paths or ())
    bindings: list[EffectAudioBinding] = []
    for index, raw_line in enumerate(str(audio_tags or "").splitlines()):
        line = raw_line.strip()
        if not line or index >= len(paths) or not paths[index]:
            continue
        if "：" in line:
            keyword_block = line.split("：", 1)[-1].strip()
        elif ":" in line:
            keyword_block = line.split(":", 1)[-1].strip()
        else:
            keyword_block = line
        audio_path = str(paths[index])
        seen_keywords: set[str] = set()
        for part in _KEYWORD_SEPARATOR_RE.split(keyword_block):
            keyword = part.strip()
            key = keyword.casefold()
            if not keyword or key in seen_keywords:
                continue
            seen_keywords.add(key)
            bindings.append(
                EffectAudioBinding(keyword=keyword, audio_path=audio_path)
            )
    return tuple(bindings)
