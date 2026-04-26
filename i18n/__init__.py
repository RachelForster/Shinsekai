"""
运行时界面文案（英语 / 简体中文 / 日语）。

用法:
    from i18n import tr, init_i18n
    init_i18n("zh_CN")  # 应用启动时从 system_config.ui_language 读取
    label.setText(tr("main.window_title"))
    tr("greeting.hello", name="User")  # 文案中可用 {name}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "SUPPORTED_LANGS",
    "tr",
    "init_i18n",
    "current_language",
    "normalize_lang",
]

SUPPORTED_LANGS: tuple[str, ...] = ("zh_CN", "en", "ja")

_bundles: dict[str, dict[str, Any]] = {}
_current: str = "zh_CN"
_locales_dir = Path(__file__).resolve().parent / "locales"


def _load_json(code: str) -> dict[str, Any]:
    path = _locales_dir / f"{code}.json"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _walk(d: dict[str, Any], key_path: str) -> Any:
    cur: Any = d
    for part in key_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _resolve(key: str, lang: str) -> str | None:
    b = _bundles.get(lang)
    if b is not None:
        v = _walk(b, key)
        if isinstance(v, str):
            return v
    return None


def tr(key: str, **kwargs: Any) -> str:
    """取当前语言；缺失则回退到英文再回退到 key。"""
    s = _resolve(key, _current) or _resolve(key, "en")
    if s is None or s == "":
        s = key
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return s


def current_language() -> str:
    return _current


def normalize_lang(code: str | None) -> str:
    if not code:
        return "zh_CN"
    c = str(code).strip().replace("-", "_")
    low = c.lower()
    if low in ("zh", "zh_cn", "chinese", "cmn", "hans"):
        return "zh_CN"
    if low in ("en", "eng", "english"):
        return "en"
    if low in ("ja", "jp", "jpn", "japanese"):
        return "ja"
    if c in SUPPORTED_LANGS:
        return c
    return "zh_CN"


def init_i18n(lang: str | None) -> str:
    """加载或切换语言。返回归一化后的语言代码。"""
    global _current
    n = normalize_lang(lang)
    if not _bundles:
        for code in SUPPORTED_LANGS:
            _bundles[code] = _load_json(code)
    _current = n
    return n
