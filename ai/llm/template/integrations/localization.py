"""Shared template translation and language compatibility helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeAlias

from i18n import current_language
from sdk.lang import LocaleCode, normalize_lang
from sdk.voice_lang import VOICE_LANG_AUTO, normalize_voice_language, resolve_character_voice_language

from ..core.catalog import PROMPT_CATALOG

LocaleInput: TypeAlias = str | Callable[[], str] | None

# 与配置中的背景名一致，勿翻译（UI 默认选此项；旧名「透明背景」仍识别）
TRANSPARENT_BG = "透明场景"
_TRANSPARENT_ALIAS = "透明背景"


def resolve_dynamic_locale(
    locale: LocaleInput = None,
    *,
    config_manager: Any = None,
) -> LocaleCode:
    """Resolve an explicit locale code, a lazy per-turn locale callback, or active UI locale."""
    if callable(locale):
        try:
            resolved = locale()
            if resolved:
                return normalize_lang(str(resolved))
        except Exception:
            pass
    elif isinstance(locale, str) and locale.strip():
        return normalize_lang(locale)
    return resolve_template_locale(config_manager)


def resolve_template_locale(config_manager: Any = None) -> LocaleCode:
    """Resolve prompt locale from AppStores/SystemConfig/ui_language, falling back to active i18n language."""
    try:
        stores = getattr(config_manager, "stores", None)
        if stores is not None:
            system_settings = getattr(stores, "system_settings", None)
            get_settings = getattr(system_settings, "get", None)
            if callable(get_settings):
                ui_lang = getattr(get_settings(), "ui_language", None)
                if ui_lang:
                    return normalize_lang(str(ui_lang))
        direct_settings = getattr(config_manager, "system_settings", None)
        get_direct = getattr(direct_settings, "get", None)
        if callable(get_direct):
            ui_lang = getattr(get_direct(), "ui_language", None)
            if ui_lang:
                return normalize_lang(str(ui_lang))
        direct_ui_lang = getattr(config_manager, "ui_language", None)
        if isinstance(direct_ui_lang, str) and direct_ui_lang.strip():
            return normalize_lang(direct_ui_lang)
        cfg = getattr(config_manager, "config", None)
        sys_cfg = getattr(cfg, "system_config", None)
        ui_lang = getattr(sys_cfg, "ui_language", None)
        if ui_lang:
            return normalize_lang(str(ui_lang))
    except Exception:
        pass
    return normalize_lang(current_language())


def translate_template(
    key: str,
    *,
    config_manager: Any = None,
    locale: str | None = None,
    **kwargs: Any,
) -> str:
    effective_locale = (
        normalize_lang(locale)
        if locale
        else resolve_template_locale(config_manager)
    )
    return PROMPT_CATALOG.translate(f"dialog.{key}", locale=effective_locale, **kwargs)


def is_transparent_background(name: str | None) -> bool:
    if name is None:
        return True
    s = str(name).strip()
    if not s:
        return True
    return s in (TRANSPARENT_BG, _TRANSPARENT_ALIAS)


def _target_voice_key(code: str | None) -> str:
    """将 api.yaml 中的 voice_language 归一成 template_gen.voice_target_* 文案键。"""
    c = (str(code).strip() if code is not None else "") or "ja"
    normalized = normalize_voice_language(c)
    if normalized == VOICE_LANG_AUTO:
        return VOICE_LANG_AUTO
    if normalized in ("yue", "ko", "en", "zh", "ja"):
        return normalized
    n = normalize_lang(c)
    if n == "en":
        return "en"
    if n == "zh_CN":
        return "zh"
    return "ja"


def resolve_cast_voice_target(
    voice_language: str | None,
    characters: Sequence[tuple[str, Any]] | None = None,
    *,
    ui_language: str | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Resolve effective dialog voice target key and per-character language hints for ``auto``."""
    if normalize_voice_language(voice_language) != VOICE_LANG_AUTO:
        return _target_voice_key(voice_language), []

    per_char: list[tuple[str, str]] = []
    for name, char in characters or ():
        resolved = resolve_character_voice_language(
            VOICE_LANG_AUTO,
            prompt_lang=getattr(char, "prompt_lang", ""),
            prompt_text=getattr(char, "prompt_text", ""),
            fallback="",
        )
        if resolved and resolved != VOICE_LANG_AUTO:
            per_char.append((str(name), _target_voice_key(resolved)))

    distinct = {key for _, key in per_char}
    if len(distinct) == 1:
        return next(iter(distinct)), per_char
    if not distinct:
        return _target_voice_key(ui_language or "zh_CN"), []
    return VOICE_LANG_AUTO, per_char


def _ui_voice_same_lang(
    config_manager,
    characters: Sequence[tuple[str, Any]] | None = None,
) -> bool:
    """UI 语言和语音目标语言相同时返回 True（无需翻译）。"""
    try:
        ui = str(config_manager.config.system_config.ui_language or "")
        voice = str(config_manager.config.system_config.voice_language or "ja")
    except Exception:
        return False
    target, _ = resolve_cast_voice_target(voice, characters, ui_language=ui)
    if target == VOICE_LANG_AUTO:
        return False
    # 比较语种前缀：zh_CN vs zh → 都是中文
    ui_main = normalize_lang(ui).split("_")[0].lower()
    return ui_main == target


def _target_voice_display_name(
    config_manager,
    translate,
    characters: Sequence[tuple[str, Any]] | None = None,
) -> str:
    try:
        ui = str(config_manager.config.system_config.ui_language or "")
        raw = config_manager.config.system_config.voice_language
    except Exception:
        ui = ""
        raw = "ja"
    target, per_char = resolve_cast_voice_target(raw, characters, ui_language=ui)
    if target == VOICE_LANG_AUTO:
        base = translate("voice_target_auto")
        if per_char:
            sep = translate("name_sep")
            mapping = sep.join(f"{name}:{translate(f'voice_target_{key}')}" for name, key in per_char)
            return translate("voice_target_auto_map", base=base, mapping=mapping)
        return base
    return translate(f"voice_target_{target}")
