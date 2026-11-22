"""
运行时界面文案（英语 / 简体中文 / 日语）。

用法:
    from i18n import tr, init_i18n
    init_i18n("zh_CN")  # 应用启动时从 system_config.ui_language 读取
    label.setText(tr("main.window_title"))
    tr("greeting.hello", name="User")  # 文案中可用 {name}
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
from typing import Any

from sdk.lang import SUPPORTED_LANGS, normalize_lang

__all__ = [
    "LocalizedErrorStr",
    "SUPPORTED_LANGS",
    "bind_language",
    "tr",
    "tr_in_bundle",
    "init_i18n",
    "current_language",
    "err_tr",
    "is_operation_error_message",
    "normalize_lang",
]

_bundles: dict[str, dict[str, Any]] = {}
_current: str = "zh_CN"
_context_lang: ContextVar[str | None] = ContextVar("shinsekai_i18n_lang", default=None)
_locales_dir = Path(__file__).resolve().parent / "locales"

_LEGACY_ERROR_PREFIXES = (
    "名称不能为空",
    "名字不能为空",
    "未找到",
    "找不到",
    "未选择",
    "请选择",
    "请先",
    "保存失败",
    "删除失败",
    "上传失败",
    "添加失败",
    "保存图片标签失败",
    "保存背景音乐标签失败",
    "参考语音必须是",
    "自设",
)

_LEGACY_ERROR_SUBSTRINGS = (
    "保存失败",
    "删除失败",
    "上传失败",
    "添加失败",
    "未找到",
    "找不到",
    "已与其他",
    "不可重命名",
    "不能将其他角色重命名",
    "占用",
    "已被其他背景组使用",
    "背景图片不存在",
    "背景音乐不存在",
    "立绘不存在",
)


class LocalizedErrorStr(str):
    """String subclass tagging localized operation error messages for status checks."""


def _ensure_bundles(lang: str | None = None) -> None:
    for target in (lang or current_language(), "en"):
        norm = normalize_lang(target)
        if norm in _bundles:
            continue
        path = _locales_dir / f"{norm}.json"
        if path.is_file():
            _bundles[norm] = json.loads(path.read_text(encoding="utf-8"))


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
    lang = current_language()
    _ensure_bundles(lang)
    s = _resolve(key, lang) or _resolve(key, "en")
    if s is None or s == "":
        s = key
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return s


def err_tr(key: str, **kwargs: Any) -> LocalizedErrorStr:
    """Translate an operation error message and tag it as LocalizedErrorStr."""
    return LocalizedErrorStr(tr(key, **kwargs))


def is_operation_error_message(message: object) -> bool:
    """Return True if an operation status string represents a failure."""
    if isinstance(message, LocalizedErrorStr):
        return True
    if not isinstance(message, str):
        return False
    stripped = message.strip()
    if not stripped:
        return False
    return (
        stripped.startswith("❌")
        or stripped.startswith(_LEGACY_ERROR_PREFIXES)
        or any(part in stripped for part in _LEGACY_ERROR_SUBSTRINGS)
    )


def tr_in_bundle(key: str, bundle: str, **kwargs: Any) -> str:
    """从指定语言包取文案（如 ``zh_CN``），不改变当前界面语言。缺失则回退英文再 key。"""
    if not _bundles:
        for code in SUPPORTED_LANGS:
            _bundles[code] = _load_json(code)
    code = bundle if bundle in SUPPORTED_LANGS else normalize_lang(bundle)
    s = _resolve(key, code) or _resolve(key, "en")
    if s is None or s == "":
        s = key
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return s


def current_language() -> str:
    ctx = _context_lang.get()
    if ctx is not None:
        return ctx
    return _current


@contextmanager
def bind_language(lang: str | None) -> Iterator[None]:
    """Bind the active UI language for the current execution context."""
    if not lang:
        yield
        return
    norm = normalize_lang(lang)
    _ensure_bundles(norm)
    token = _context_lang.set(norm)
    try:
        yield
    finally:
        _context_lang.reset(token)


def init_i18n(lang: str | None) -> str:
    """加载或切换语言。返回归一化后的语言代码。"""
    global _current
    n = normalize_lang(lang)
    if not _bundles:
        for code in SUPPORTED_LANGS:
            _bundles[code] = _load_json(code)
    _current = n
    return n
