"""Tracked fallback manifests for built-in UI themes.

Runtime data under ``data/`` is intentionally ignored. These manifests keep the
built-in theme contract available in clean checkouts and packaged builds.
"""

from __future__ import annotations

from typing import Any, Dict


def _dark_logs() -> Dict[str, Any]:
    return {
        "page": {"color": "#f7f3ff"},
        "panel": {
            "background": "rgba(20,20,28,0.78)",
            "borderColor": "rgba(255,255,255,0.16)",
            "borderRadius": "8px",
            "color": "#f7f3ff",
            "boxShadow": "0 18px 36px rgba(0,0,0,0.22)",
        },
        "toolbar": {
            "background": "rgba(26,26,36,0.9)",
            "borderColor": "rgba(255,255,255,0.16)",
            "color": "#f7f3ff",
        },
        "sidebar": {
            "background": "rgba(18,18,26,0.84)",
            "borderColor": "rgba(255,255,255,0.14)",
            "color": "#f7f3ff",
        },
        "source": {
            "background": "rgba(100,74,227,0.14)",
            "borderColor": "rgba(156,140,255,0.44)",
            "color": "#cfc7ff",
        },
        "viewer": {
            "background": "rgba(12,12,18,0.82)",
            "borderColor": "rgba(255,255,255,0.14)",
            "color": "#f7f3ff",
        },
        "code": {
            "background": "rgba(8,9,14,0.9)",
            "color": "#f3f0ff",
            "fontFamily": "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        },
        "line": {
            "borderColor": "rgba(255,255,255,0.08)",
            "hover": {"background": "rgba(100,74,227,0.1)"},
            "expanded": {"background": "rgba(100,74,227,0.15)"},
        },
        "number": {
            "borderColor": "rgba(255,255,255,0.1)",
            "color": "rgba(226,220,255,0.5)",
        },
        "detail": {
            "background": "rgba(255,255,255,0.05)",
            "borderColor": "rgba(255,255,255,0.12)",
            "color": "#e9e4ff",
        },
        "badge": {
            "background": "rgba(255,255,255,0.05)",
            "borderColor": "rgba(255,255,255,0.12)",
            "color": "rgba(239,235,255,0.72)",
        },
        "event": {
            "background": "rgba(100,74,227,0.16)",
            "borderColor": "rgba(156,140,255,0.4)",
            "color": "#cfc7ff",
        },
        "fileItem": {
            "background": "rgba(255,255,255,0.03)",
            "borderColor": "rgba(255,255,255,0.1)",
            "color": "#f7f3ff",
            "hover": {"background": "rgba(255,255,255,0.07)", "borderColor": "rgba(255,255,255,0.18)"},
            "active": {
                "background": "rgba(100,74,227,0.18)",
                "borderColor": "rgba(156,140,255,0.48)",
                "color": "#d8d1ff",
            },
        },
        "levels": {
            "error": {"background": "rgba(255,95,109,0.14)", "borderColor": "rgba(255,95,109,0.48)", "color": "#ff9ca7"},
            "warn": {"background": "rgba(237,168,64,0.13)", "borderColor": "rgba(237,168,64,0.48)", "color": "#f2c779"},
            "info": {"background": "rgba(64,196,141,0.12)", "borderColor": "rgba(64,196,141,0.4)", "color": "#8de0b9"},
            "debug": {"background": "rgba(91,173,255,0.1)", "borderColor": "rgba(91,173,255,0.34)", "color": "#9bcbff"},
            "default": {"background": "rgba(255,255,255,0.05)", "borderColor": "rgba(255,255,255,0.12)", "color": "rgba(239,235,255,0.72)"},
        },
    }


def _light_logs() -> Dict[str, Any]:
    return {
        "page": {"color": "#2a2730"},
        "panel": {
            "background": "rgba(255,255,255,0.88)",
            "borderColor": "rgba(66,50,92,0.14)",
            "borderRadius": "8px",
            "color": "#2a2730",
            "boxShadow": "0 14px 32px rgba(75,55,110,0.1)",
        },
        "toolbar": {
            "background": "rgba(255,255,255,0.92)",
            "borderColor": "rgba(66,50,92,0.14)",
            "color": "#2a2730",
        },
        "sidebar": {
            "background": "rgba(255,255,255,0.82)",
            "borderColor": "rgba(66,50,92,0.12)",
            "color": "#2a2730",
        },
        "source": {
            "background": "rgba(199,125,255,0.12)",
            "borderColor": "rgba(157,78,221,0.28)",
            "color": "#7930b2",
        },
        "viewer": {
            "background": "rgba(255,255,255,0.9)",
            "borderColor": "rgba(66,50,92,0.14)",
            "color": "#2a2730",
        },
        "code": {
            "background": "rgba(253,251,255,0.95)",
            "color": "#302a3a",
            "fontFamily": "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        },
        "line": {
            "borderColor": "rgba(66,50,92,0.1)",
            "hover": {"background": "rgba(199,125,255,0.08)"},
            "expanded": {"background": "rgba(199,125,255,0.12)"},
        },
        "number": {
            "borderColor": "rgba(66,50,92,0.1)",
            "color": "rgba(42,39,48,0.48)",
        },
        "detail": {
            "background": "rgba(246,241,255,0.9)",
            "borderColor": "rgba(66,50,92,0.12)",
            "color": "#302a3a",
        },
        "badge": {
            "background": "rgba(246,241,255,0.78)",
            "borderColor": "rgba(66,50,92,0.12)",
            "color": "rgba(42,39,48,0.66)",
        },
        "event": {
            "background": "rgba(199,125,255,0.14)",
            "borderColor": "rgba(157,78,221,0.28)",
            "color": "#7930b2",
        },
        "fileItem": {
            "background": "rgba(255,255,255,0.58)",
            "borderColor": "rgba(66,50,92,0.12)",
            "color": "#2a2730",
            "hover": {"background": "rgba(246,241,255,0.9)", "borderColor": "rgba(157,78,221,0.22)"},
            "active": {
                "background": "rgba(199,125,255,0.14)",
                "borderColor": "rgba(157,78,221,0.32)",
                "color": "#7930b2",
            },
        },
        "levels": {
            "error": {"background": "rgba(217,70,86,0.1)", "borderColor": "rgba(217,70,86,0.3)", "color": "#b42a3d"},
            "warn": {"background": "rgba(188,118,28,0.12)", "borderColor": "rgba(188,118,28,0.34)", "color": "#985f16"},
            "info": {"background": "rgba(38,141,101,0.1)", "borderColor": "rgba(38,141,101,0.28)", "color": "#217a58"},
            "debug": {"background": "rgba(47,116,190,0.1)", "borderColor": "rgba(47,116,190,0.26)", "color": "#2f6eae"},
            "default": {"background": "rgba(246,241,255,0.78)", "borderColor": "rgba(66,50,92,0.12)", "color": "rgba(42,39,48,0.66)"},
        },
    }


BUILTIN_THEME_MANIFESTS: Dict[str, Dict[str, Any]] = {
    "classic-dark": {
        "schema": 1,
        "id": "classic-dark",
        "name": {"zh_CN": "经典暗色", "en": "Classic Dark", "ja": "クラシック・ダーク"},
        "author": "Shinsekai",
        "version": "1.0.0",
        "description": {
            "zh_CN": "默认深色主题，半透明对话框",
            "en": "Default dark theme with a translucent dialog box",
        },
        "tokens": {
            "global": {"themeColor": "#644ae3"},
            "dialog": {
                "background": "rgba(20,20,28,0.86)",
                "borderColor": "rgba(255,255,255,0.32)",
                "borderRadius": "8px",
                "color": "#ffffff",
                "padding": 40,
                "widthPct": 86,
                "offsetY": 0,
                "boxShadow": "0 16px 44px rgba(0,0,0,0.5)",
            },
            "options": {
                "background": "rgba(50,50,50,0.68)",
                "borderColor": "rgba(255,255,255,0.28)",
                "color": "#ffffff",
                "gap": 10,
                "hover": {"background": "rgba(70,70,70,0.74)"},
            },
            "input": {
                "background": "rgba(34,34,40,0.9)",
                "borderColor": "rgba(255,255,255,0.22)",
                "fieldBackground": "rgba(50,50,50,0.78)",
                "color": "#ffffff",
            },
            "toolbar": {"background": "rgba(34,34,40,0.9)", "borderColor": "rgba(255,255,255,0.22)", "color": "#ffffff"},
            "send": {"background": "#644ae3", "color": "#ffffff"},
            "name": {"color": "#9c8cff"},
            "logs": _dark_logs(),
            "typewriter": {"cps": 40},
        },
    },
    "light-paper": {
        "schema": 1,
        "id": "light-paper",
        "name": {"zh_CN": "浅色纸张", "en": "Light Paper", "ja": "ライトペーパー"},
        "author": "Shinsekai",
        "version": "1.0.0",
        "description": {
            "zh_CN": "明亮纸张风格，适合白天",
            "en": "Bright paper-like theme for daytime",
        },
        "tokens": {
            "global": {"themeColor": "#c77dff"},
            "dialog": {
                "background": "rgba(250,248,244,0.92)",
                "borderColor": "rgba(0,0,0,0.16)",
                "borderRadius": "12px",
                "color": "#2a2730",
                "padding": 36,
                "widthPct": 82,
                "offsetY": 0,
                "boxShadow": "0 12px 36px rgba(0,0,0,0.18)",
            },
            "options": {
                "background": "rgba(255,255,255,0.86)",
                "borderColor": "rgba(0,0,0,0.14)",
                "color": "#2a2730",
                "gap": 10,
                "hover": {"background": "rgba(240,236,250,0.94)"},
            },
            "input": {
                "background": "rgba(255,255,255,0.9)",
                "borderColor": "rgba(0,0,0,0.14)",
                "fieldBackground": "rgba(255,255,255,0.96)",
                "color": "#2a2730",
            },
            "toolbar": {"background": "rgba(255,255,255,0.9)", "borderColor": "rgba(0,0,0,0.14)", "color": "#2a2730"},
            "send": {"background": "#c77dff", "color": "#ffffff"},
            "name": {"color": "#9d4edd"},
            "logs": _light_logs(),
            "typewriter": {"cps": 36},
        },
    },
}
