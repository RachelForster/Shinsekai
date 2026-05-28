from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def _optional_suffix_check(value: str, suffix: str, label: str) -> tuple[bool, str]:
    if not value:
        return True, ""
    if value.lower().endswith(suffix):
        return True, ""
    return False, f"{label}: 文件后缀应为 {suffix}"


def _path_namespace_list(paths: Any) -> list[Any]:
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    out = []
    for item in paths:
        path = str(item or "").strip()
        if path:
            out.append(SimpleNamespace(name=path))
    if not out:
        raise ValueError("at least one path is required")
    return out


def _tag_content(text: Any) -> str:
    value = str(text or "")
    if "：" in value:
        return value.split("：", 1)[1].strip()
    if ":" in value:
        return value.split(":", 1)[1].strip()
    return value.strip()
