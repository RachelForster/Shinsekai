"""Base context shared by prompt sections, independent of chat or model APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sdk.lang import LocaleCode, Translator


@dataclass(frozen=True)
class TemplateContext:
    """Extend with typed fields for a particular system or user prompt.

    Contexts are passed at render time, never stored on sections. Frozen
    dataclass subclasses can use ``dataclasses.replace`` to derive a context
    for one subtree without changing its siblings' input.
    """

    locale: LocaleCode = field(default="zh_CN", kw_only=True)
    translator: Translator | None = field(default=None, kw_only=True)

    def tr(self, key: str, **kwargs: Any) -> str:
        """Resolve a localized prompt catalog key using the injected translator or active locale."""
        if self.translator is not None:
            return self.translator(key, **kwargs)
        from .catalog import PROMPT_CATALOG

        return PROMPT_CATALOG.translate(key, locale=self.locale, **kwargs)
