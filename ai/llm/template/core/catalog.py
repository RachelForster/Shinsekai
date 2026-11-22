"""YAML-backed prompt catalog with thread-safe lazy loading and fallback resolution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

import yaml

from sdk.lang import LocaleCode, SUPPORTED_LANGS, Translator, normalize_lang


def _default_catalog_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "catalog"


def _flatten_yaml(data: Any, prefix: str = "") -> dict[str, str]:
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ValueError(
            f"Prompt catalog entry {prefix!r} must be a mapping or string, got {type(data).__name__}"
        )
    entries: dict[str, str] = {}
    for raw_key, value in data.items():
        key_part = str(raw_key)
        full_key = f"{prefix}.{key_part}" if prefix else key_part
        if isinstance(value, Mapping):
            entries.update(_flatten_yaml(value, full_key))
        elif isinstance(value, str):
            entries[full_key] = value
        else:
            raise ValueError(
                f"Prompt catalog entry {full_key!r} must be a string, got {type(value).__name__}"
            )
    return entries


class PromptCatalog:
    """Thread-safe reader for built-in prompt YAML catalogs organized by locale and domain."""

    def __init__(self, catalog_dir: Path | None = None) -> None:
        self._catalog_dir = catalog_dir or _default_catalog_dir()
        self._lock = RLock()
        self._cache: dict[LocaleCode, dict[str, str]] = {}

    @property
    def catalog_dir(self) -> Path:
        return self._catalog_dir

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _load_locale(self, locale: LocaleCode) -> dict[str, str]:
        with self._lock:
            cached = self._cache.get(locale)
            if cached is not None:
                return cached
            locale_dir = self._catalog_dir / locale
            entries: dict[str, str] = {}
            if locale_dir.is_dir():
                for yaml_path in sorted(locale_dir.glob("*.yaml")):
                    domain = yaml_path.stem
                    loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                    entries.update(_flatten_yaml(loaded, domain))
            self._cache[locale] = entries
            return entries

    def domains(self, locale: str = "zh_CN") -> tuple[str, ...]:
        loc = normalize_lang(locale)
        locale_dir = self._catalog_dir / loc
        if not locale_dir.is_dir():
            return ()
        return tuple(path.stem for path in sorted(locale_dir.glob("*.yaml")))

    def keys(self, locale: str = "zh_CN", domain: str | None = None) -> tuple[str, ...]:
        loc = normalize_lang(locale)
        entries = self._load_locale(loc)
        if domain is None:
            return tuple(entries.keys())
        prefix = f"{domain}."
        return tuple(k for k in entries if k.startswith(prefix))

    def raw(self, key: str, *, locale: str = "zh_CN") -> str | None:
        """Return raw template string from exact locale without fallback."""
        loc = normalize_lang(locale)
        return self._load_locale(loc).get(key)

    def translate(
        self,
        key: str,
        *,
        locale: str | None = "zh_CN",
        strict: bool = False,
        **kwargs: Any,
    ) -> str:
        loc = normalize_lang(locale)
        raw_text = self._load_locale(loc).get(key)
        if raw_text is None:
            if strict:
                raise KeyError(f"Missing prompt key {key!r} in locale {loc!r}")
            for fallback_loc in ("en", "zh_CN"):
                if fallback_loc != loc and fallback_loc in SUPPORTED_LANGS:
                    raw_text = self._load_locale(fallback_loc).get(key)
                    if raw_text is not None:
                        break
        if raw_text is None:
            return key
        # Zero-arg calls must bypass .format() so raw JSON schema snippets with single braces pass through intact.
        if not kwargs:
            return raw_text
        try:
            return raw_text.format(**kwargs)
        except (KeyError, ValueError):
            if strict:
                raise
            return raw_text

    def translator(self, locale: str | None, *, strict: bool = False) -> Translator:
        loc = normalize_lang(locale)

        def _translate(key: str, **kwargs: Any) -> str:
            return self.translate(key, locale=loc, strict=strict, **kwargs)

        return _translate


PROMPT_CATALOG = PromptCatalog()

__all__ = ["PROMPT_CATALOG", "PromptCatalog"]
