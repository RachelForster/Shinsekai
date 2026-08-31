from __future__ import annotations

from typing import Any


def _tag_content(text: Any) -> str:
    value = str(text or "")
    if "：" in value:
        return value.split("：", 1)[1].strip()
    if ":" in value:
        return value.split(":", 1)[1].strip()
    return value.strip()
