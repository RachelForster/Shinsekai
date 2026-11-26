"""Declarative specification pairing prompt section builders with language policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Generic, TypeVar

from sdk.lang import LocaleCode, normalize_lang

from .context import TemplateContext
from .section import Section


SystemCtxT = TypeVar("SystemCtxT", bound=TemplateContext)
UserCtxT = TypeVar("UserCtxT", bound=TemplateContext)


class PromptLanguagePolicy(str, Enum):
    """Controls whether a prompt follows SystemConfig.ui_language or stays contract-locked."""

    FOLLOW_UI = "follow_ui"
    LOCKED_CONTRACT = "locked_contract"


@dataclass(frozen=True)
class PromptSpec(Generic[SystemCtxT, UserCtxT]):
    """Pairs system/user section builders with an explicit locale resolution policy."""

    id: str
    language_policy: PromptLanguagePolicy = PromptLanguagePolicy.FOLLOW_UI
    locked_locale: LocaleCode | None = None
    system_builder: Callable[[], Section[SystemCtxT]] | None = None
    user_builder: Callable[[], Section[UserCtxT]] | None = None

    def resolve_locale(self, ui_locale: str | None) -> LocaleCode:
        if self.language_policy == PromptLanguagePolicy.LOCKED_CONTRACT:
            return normalize_lang(self.locked_locale or "en")
        return normalize_lang(ui_locale)

    def render_system(self, context: SystemCtxT) -> str:
        if self.system_builder is None:
            raise ValueError(f"PromptSpec {self.id!r} has no system_builder")
        effective = self.resolve_locale(context.locale)
        if effective != context.locale:
            context = replace(context, locale=effective)
        return self.system_builder().render(context)

    def render_user(self, context: UserCtxT) -> str:
        if self.user_builder is None:
            raise ValueError(f"PromptSpec {self.id!r} has no user_builder")
        effective = self.resolve_locale(context.locale)
        if effective != context.locale:
            context = replace(context, locale=effective)
        return self.user_builder().render(context)


__all__ = ["PromptLanguagePolicy", "PromptSpec"]
