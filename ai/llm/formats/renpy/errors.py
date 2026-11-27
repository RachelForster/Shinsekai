"""Structured, localized parser error descriptors for `renpy_v1`."""

from __future__ import annotations

from dataclasses import dataclass

from i18n import current_language, tr_in_bundle
from sdk.lang import normalize_lang


@dataclass(frozen=True, slots=True)
class RenpyParseError:
    """Immutable structured parse error carrying an i18n key and format args."""

    code: str
    params: tuple[tuple[str, str], ...] = ()

    def params_dict(self) -> dict[str, str]:
        """Return parameter mapping suitable for translation interpolation."""
        return dict(self.params)


def renpy_error(code: str, **params: object) -> RenpyParseError:
    """Create a structured `RenpyParseError` under `desktop.renpy_parse.<code>`."""
    return RenpyParseError(
        code=code,
        params=tuple((str(k), str(v)) for k, v in params.items()),
    )


def format_renpy_parse_error(
    error: RenpyParseError,
    *,
    locale: str | None = None,
) -> str:
    """Render `error` in `locale` (or the active context/bundle language)."""
    resolved = normalize_lang(locale) if locale else normalize_lang(current_language())
    return tr_in_bundle(
        f"desktop.renpy_parse.{error.code}",
        resolved,
        **error.params_dict(),
    )


__all__ = [
    "RenpyParseError",
    "format_renpy_parse_error",
    "renpy_error",
]
