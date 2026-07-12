"""Tracked fallback manifests for the built-in chat UI themes.

The packaged runtime also carries the full manifests under
``assets/chat_ui_themes``. This module keeps minimal fallbacks available when
those directories are absent, while preferring each bundled ``theme.json`` as
the single full manifest source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_BUILTIN_CHAT_THEME_ID = "windborne-adventure"
NEON_NIGHT_CITY_THEME_ID = "neon-night-city"


_WINDBORNE_FALLBACK_MANIFEST: Dict[str, Any] = {
    "schema": 1,
    "id": DEFAULT_BUILTIN_CHAT_THEME_ID,
    "name": {
        "zh_CN": "风旅冒险",
        "en": "Windborne Adventure",
        "ja": "風渡りアドベンチャー",
    },
    "author": "Shinsekai",
    "version": "1.0.0",
    "description": {
        "zh_CN": "参考蓝天山野冒险截图制作的 ADV 风格主题。",
        "en": "An open-sky adventure ADV theme.",
        "ja": "青空と山岳の冒険画面を参考にしたADV風テーマ。",
    },
    "tokens": {
        "global": {"themeColor": "#f3cf57", "fontFamily": "Georgia, Times New Roman, serif"},
        "dialog": {
            "background": "rgba(0,0,0,0)",
            "borderColor": "rgba(231,188,62,0.0)",
            "borderRadius": "4px",
            "boxShadow": "none",
            "chrome": "none",
            "color": "#ffffff",
            "heightPx": 166,
            "nameInputGapVh": 20,
            "padding": 8,
            "textAlign": "center",
            "textShadow": "0 2px 0 #26313a, 0 -1px 0 #26313a, 1px 0 0 #26313a, -1px 0 0 #26313a, 0 4px 8px rgba(0,0,0,0.72)",
            "textSizePx": 34,
            "textWeight": 800,
            "widthPct": 72,
        },
        "name": {
            "align": "center",
            "color": "#f3cf57",
            "decoration": "line-dots",
            "fontFamily": "Trebuchet MS, Georgia, Times New Roman, serif",
            "hideWhenStartOption": True,
            "textShadow": "0 2px 0 #5a3a0c, 0 3px 6px rgba(0,0,0,0.62)",
            "textSizePx": 24,
            "textWeight": 800,
        },
        "options": {
            "background": "rgba(38,51,64,0.74)",
            "borderColor": "rgba(244,250,255,0.28)",
            "borderRadius": "999px",
            "boxShadow": "0 10px 24px rgba(0,0,0,0.28)",
            "color": "#ffffff",
            "gap": 14,
            "active": {"background": "#f3cf57", "borderColor": "rgba(255,255,255,0.62)", "color": "#1d2630"},
            "hover": {"background": "#f3cf57", "borderColor": "rgba(255,255,255,0.62)", "color": "#1d2630"},
            "icon": "chat",
            "maxWidthVw": 38,
            "minHeightPx": 52,
            "minHeightVh": 5.2,
            "minWidthVw": 25.5,
            "nameClearanceVh": 5.6,
            "placement": "right",
            "textShadow": "0 2px 4px rgba(0,0,0,0.58)",
            "textSizeVh": 1.62,
            "textSizePx": 24,
            "textWeight": 800,
            "widthMode": "content",
        },
        "input": {
            "background": "rgba(87,91,104,0.9)",
            "borderColor": "rgba(244,250,255,0)",
            "borderRadius": "999px",
            "boxShadow": "0 14px 34px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.16)",
            "color": "#ffffff",
            "fieldBackground": "transparent",
            "fieldBorderRadius": "0px",
            "layout": "pill",
            "maxWidthPx": 640,
            "sendPlacement": "inside",
        },
        "toolbar": {
            "background": "rgba(31,42,52,0.72)",
            "borderColor": "rgba(244,250,255,0.22)",
            "borderRadius": "999px",
            "color": "#ffffff",
            "placement": "input-top",
            "reveal": "hover",
        },
        "send": {
            "background": "rgba(0,0,0,0)",
            "borderColor": "rgba(255,255,255,0)",
            "borderRadius": "10px",
            "color": "#f3cf57",
        },
        "typewriter": {"cps": 34},
    },
}


_NEON_NIGHT_CITY_FALLBACK_MANIFEST: Dict[str, Any] = {
    "schema": 1,
    "id": NEON_NIGHT_CITY_THEME_ID,
    "name": {
        "zh_CN": "霓虹夜城",
        "en": "Neon Night City",
        "ja": "ネオン・ナイトシティ",
    },
    "author": "Shinsekai",
    "version": "1.0.0",
    "description": {
        "zh_CN": "青色与洋红霓虹组成的赛博朋克聊天主题。",
        "en": "A cyberpunk chat theme built from cyan and magenta neon.",
        "ja": "シアンとマゼンタのネオンで構成したサイバーパンクテーマ。",
    },
    "tokens": {
        "global": {
            "themeColor": "#00f5ff",
            "fontFamily": "Rajdhani, Bahnschrift, Segoe UI, sans-serif",
        },
        "dialog": {
            "background": "rgba(2,8,20,0.94)",
            "borderColor": "rgba(0,245,255,0.72)",
            "borderRadius": "6px",
            "boxShadow": "0 0 24px rgba(0,245,255,0.2)",
            "chrome": "panel",
            "color": "#e9fbff",
        },
        "options": {
            "background": "rgba(3,12,28,0.96)",
            "borderColor": "rgba(0,245,255,0.74)",
            "borderRadius": "4px",
            "color": "#e9fbff",
            "hover": {
                "background": "rgba(255,45,163,0.9)",
                "borderColor": "#ff9bd3",
                "color": "#ffffff",
            },
            "placement": "center",
            "widthMode": "fixed",
            "widthPx": 700,
        },
        "input": {
            "background": "rgba(2,8,20,0.96)",
            "borderColor": "rgba(0,245,255,0.72)",
            "borderRadius": "6px",
            "color": "#e9fbff",
            "maxWidthPx": 700,
            "sendPlacement": "inside",
        },
        "name": {
            "align": "left",
            "color": "#ff63bb",
            "decoration": "accent",
            "fontFamily": "Cascadia Mono, JetBrains Mono, Consolas, monospace",
            "textSizePx": 19,
            "textWeight": 800,
        },
        "typewriter": {"cps": 42},
    },
}


def _load_bundled_manifest(theme_id: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    manifest_path = Path(__file__).resolve().parents[1] / "assets" / "chat_ui_themes" / theme_id / "theme.json"
    try:
        with manifest_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    if not isinstance(data, dict):
        return dict(fallback)
    data.pop("$schema", None)
    return data


BUILTIN_THEME_MANIFESTS: Dict[str, Dict[str, Any]] = {
    DEFAULT_BUILTIN_CHAT_THEME_ID: _load_bundled_manifest(
        DEFAULT_BUILTIN_CHAT_THEME_ID, _WINDBORNE_FALLBACK_MANIFEST
    ),
    NEON_NIGHT_CITY_THEME_ID: _load_bundled_manifest(
        NEON_NIGHT_CITY_THEME_ID, _NEON_NIGHT_CITY_FALLBACK_MANIFEST
    ),
}
