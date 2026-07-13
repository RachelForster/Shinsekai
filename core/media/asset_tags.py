from __future__ import annotations

import re


_TAG_PREFIX_RE = re.compile(r"^\s*(?:tags?|标签|標籤)\s*[:：]\s*", re.IGNORECASE)


def tag_contents(block: str, count: int) -> list[str]:
    """Return one tag value per asset while accepting legacy numbered blocks."""
    lines = [line for line in str(block or "").splitlines() if line.strip()]
    values: list[str] = []
    for line in lines[: max(0, count)]:
        full_width = line.find("：")
        ascii_colon = line.find(":")
        indexes = [index for index in (full_width, ascii_colon) if index >= 0]
        values.append(line[min(indexes) + 1 :].strip() if indexes else line.strip())
    values.extend([""] * (max(0, count) - len(values)))
    return values


def numbered_tags(prefix: str, tags: list[str]) -> str:
    if not tags:
        return ""
    return "\n".join(f"{prefix} {index + 1}：{tag.strip()}" for index, tag in enumerate(tags)) + "\n"


def normalize_generated_tags(value: object, *, max_chars: int = 240) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    text = _TAG_PREFIX_RE.sub("", text)
    text = text.strip(" \t\r\n\"'`[]")
    text = re.sub(r"[\r\n;；|]+", ",", text)
    text = re.sub(r"\s*[,，]\s*", ", ", text)
    text = re.sub(r"(?:,\s*){2,}", ", ", text).strip(",。 ")
    return text[:max_chars].rstrip(", ")
