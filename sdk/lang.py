"""Language codes shared by the app and plugins (normalization, supported set)."""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypeAlias

LocaleCode: TypeAlias = Literal["zh_CN", "en", "ja"]
SUPPORTED_LANGS: tuple[LocaleCode, ...] = ("zh_CN", "en", "ja")

__all__ = [
    "LocaleCode",
    "SUPPORTED_LANGS",
    "Translator",
    "normalize_lang",
]


class Translator(Protocol):
    """Callable translator contract taking a catalog key and format kwargs."""

    def __call__(self, key: str, **kwargs: Any) -> str: ...


def normalize_lang(code: str | None) -> LocaleCode:
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
    if c == "zh_CN":
        return "zh_CN"
    if c == "en":
        return "en"
    if c == "ja":
        return "ja"
    return "zh_CN"
