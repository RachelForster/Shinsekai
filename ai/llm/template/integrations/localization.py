"""Shared template translation and language compatibility helpers."""

from __future__ import annotations

from typing import Any

from i18n import current_language
from sdk.lang import LocaleCode, normalize_lang

from ..core.catalog import PROMPT_CATALOG

# 与配置中的背景名一致，勿翻译（UI 默认选此项；旧名「透明背景」仍识别）
TRANSPARENT_BG = "透明场景"
_TRANSPARENT_ALIAS = "透明背景"


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
    low = c.lower()
    if low in ("yue", "yue_hk", "cantonese", "cht", "zh_hk"):
        return "yue"
    n = normalize_lang(c)
    if n == "en":
        return "en"
    if n == "zh_CN":
        return "zh"
    return "ja"


def _ui_voice_same_lang(config_manager) -> bool:
    """UI 语言和语音目标语言相同时返回 True（无需翻译）。"""
    try:
        ui = str(config_manager.config.system_config.ui_language or "")
        voice = str(config_manager.config.system_config.voice_language or "ja")
    except Exception:
        return False
    # 比较语种前缀：zh_CN vs zh → 都是中文
    ui_main = ui.split("_")[0].lower()
    voice_main = _target_voice_key(voice)
    return ui_main == voice_main


def _target_voice_display_name(config_manager, translate) -> str:
    try:
        raw = config_manager.config.system_config.voice_language
    except Exception:
        raw = "ja"
    return translate(f"voice_target_{_target_voice_key(raw)}")
