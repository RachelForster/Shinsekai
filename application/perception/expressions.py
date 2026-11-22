"""Map a reaction's expression to the character's configured sprite index."""

from pathlib import PurePath
import re
from typing import Any, Mapping, Sequence

from core.sprite.selection import sprite_entry_path


_TAG_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:(?:sprite|立绘|立繪|表情)\s*)?(\d+)\s*[:：、.)=|]\s*(.+)$", re.I)
_TAG_SEPARATORS = re.compile(r"[\s，,、/;；|]+")
_EXPRESSION_TAGS = {
    "平静": ("平静", "平靜", "冷静", "冷靜", "平淡", "沉静", "沉靜", "放松", "放鬆", "镇定", "鎮定", "无表情", "無表情", "严肃", "嚴肅", "calm", "neutral", "serious"),
    "开心": ("开心", "開心", "愉快", "喜悦", "喜悅", "笑", "微笑", "大笑", "欢笑", "歡笑", "兴奋", "興奮", "得意", "happy", "smile", "laugh", "grin"),
    "惊讶": ("惊讶", "驚訝", "吃惊", "吃驚", "震惊", "震驚", "惊喜", "驚喜", "诧异", "詫異", "愣住", "目瞪", "surprise", "shock", "gasp", "驚き"),
    "好奇": ("好奇", "疑惑", "困惑", "疑问", "疑問", "思考", "思索", "思虑", "思慮", "沉思", "专注", "專注", "投入", "curious", "puzzled", "confused", "think"),
    "担心": ("担心", "擔心", "担忧", "擔憂", "忧虑", "憂慮", "紧张", "緊張", "恐惧", "恐懼", "慌张", "worried", "scared", "nervous", "心配"),
    "难过": ("难过", "難過", "悲伤", "悲傷", "伤心", "傷心", "沮丧", "沮喪", "失落", "流泪", "落泪", "sad", "cry", "悲し"),
    "生气": ("生气", "生氣", "愤怒", "憤怒", "不满", "不滿", "恼火", "惱火", "angry", "mad", "annoyed", "怒り"),
    "害羞": ("害羞", "羞涩", "羞澀", "脸红", "臉紅", "腼腆", "靦腆", "shy", "blush", "embarrassed", "照れ"),
}


def canonical_expression(value: str) -> str:
    key = value.strip().strip("。！!、 ").casefold()
    return next((name for name, aliases in _EXPRESSION_TAGS.items() if key == name or key in aliases), "")


def _sprite_descriptions(emotion_tags: str) -> dict[int, str]:
    entries = [match.groups() for line in emotion_tags.splitlines() if (match := _TAG_LINE.match(line))]
    index_offset = 0 if any(int(number) == 0 for number, _ in entries) else 1
    return {int(number) - index_offset: " ".join(text.split()) for number, text in entries}


def expression_sprite_candidates(sprites: Sequence[Any], emotion_tags: str) -> dict[str, tuple[int, ...]]:
    """Group distinct assets by expression, preferring explicit labels to filenames."""
    descriptions = _sprite_descriptions(emotion_tags)
    assets = []
    for index, sprite in enumerate(sprites):
        path = sprite_entry_path(sprite)
        if path:
            path_key = str(PurePath(path)).replace("\\", "/").casefold()
            label = descriptions.get(index, "").casefold()
            words = _TAG_SEPARATORS.split(label)
            assets.append((index, path_key, label, words, PurePath(path).stem.casefold()))

    choices: dict[str, tuple[int, ...]] = {}
    for expression, tags in _EXPRESSION_TAGS.items():
        matches: list[tuple[int, int, str]] = []
        for index, path_key, label, words, filename in assets:
            if words[0] in tags:
                matches.append((0, index, path_key))
            elif any(tag in words for tag in tags):
                matches.append((1, index, path_key))
            elif any(len(tag) > 1 and tag in label for tag in tags):
                matches.append((2, index, path_key))
            elif any(len(tag) > 1 and tag in filename for tag in tags):
                matches.append((3, index, path_key))
        if matches:
            unique_paths: dict[str, int] = {}
            for _score, index, path_key in sorted(matches):
                unique_paths.setdefault(path_key, index)
            choices[expression] = tuple(unique_paths.values())
    return choices


def sprite_prompt_choices(
    sprites: Sequence[Any],
    emotion_tags: str,
    expressions: Mapping[str, tuple[int, ...]],
) -> dict[int, str]:
    """List a compact, diverse set of labeled assets using their one-based positions."""
    descriptions = _sprite_descriptions(emotion_tags)
    fallback = {index: emotion for emotion, indices in expressions.items() for index in indices}
    first_by_expression = [indices[0] for indices in expressions.values() if indices]
    choices: dict[int, str] = {}
    seen_paths: set[str] = set()
    for index in dict.fromkeys([*first_by_expression, *range(len(sprites))]):
        label = descriptions.get(index) or fallback.get(index)
        path = sprite_entry_path(sprites[index])
        if not label or not path:
            continue
        path_key = str(PurePath(path)).replace("\\", "/").casefold()
        if path_key not in seen_paths:
            seen_paths.add(path_key)
            choices[index + 1] = label[:36]
        if len(choices) == 16:
            break
    return choices
