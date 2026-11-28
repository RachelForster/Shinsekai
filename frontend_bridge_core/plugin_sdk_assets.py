"""Host theme CSS, UI primitives, and postMessage bridge assets for plugin iframes."""

from __future__ import annotations

import re
from pathlib import Path

from sdk.path_utils import resolve_regular_path

__all__ = [
    "SDK_ASSET_PATHS",
    "inject_plugin_sdk_into_html",
    "render_sdk_host_bridge_js",
    "render_sdk_theme_css",
    "render_sdk_ui_css",
    "resolve_sdk_asset",
]

SDK_THEME_CSS_PATH = "/api/plugins/sdk/theme.css"
SDK_UI_CSS_PATH = "/api/plugins/sdk/ui.css"
SDK_HOST_BRIDGE_JS_PATH = "/api/plugins/sdk/host-bridge.js"

SDK_ASSET_PATHS: frozenset[str] = frozenset(
    {
        SDK_THEME_CSS_PATH,
        SDK_UI_CSS_PATH,
        SDK_HOST_BRIDGE_JS_PATH,
    }
)

_HEAD_OPEN_RE = re.compile(r"(<head\b[^>]*>)", re.IGNORECASE)

_FALLBACK_THEME_CSS = """
:root {
  color-scheme: light dark;
  --theme-accent: #d4788e;
  --radius-control: 7px;
  --radius-panel: 10px;
  --radius-toast: 12px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 15px;
  --text-xl: 18px;
  --font-settings: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  --leading-tight: 1.25;
  --leading-snug: 1.35;
  --leading-normal: 1.45;
  --color-bg-app: light-dark(color-mix(in oklch, var(--theme-accent) 7%, white), color-mix(in oklch, var(--theme-accent) 14%, #0d0a0c));
  --color-bg-panel: light-dark(color-mix(in oklch, var(--theme-accent) 4%, white), color-mix(in oklch, var(--theme-accent) 10%, #181014));
  --color-bg-input: light-dark(color-mix(in oklch, var(--theme-accent) 2%, white), color-mix(in oklch, var(--theme-accent) 8%, #100b0e));
  --color-border: light-dark(color-mix(in oklch, var(--theme-accent) 24%, white), color-mix(in oklch, var(--theme-accent) 26%, #241820));
  --color-border-hover: light-dark(color-mix(in oklch, var(--theme-accent) 34%, white), color-mix(in oklch, var(--theme-accent) 36%, #2e2028));
  --color-control-hover: light-dark(color-mix(in oklch, var(--theme-accent) 16%, white), color-mix(in oklch, var(--theme-accent) 22%, #21161d));
  --color-control-active: light-dark(color-mix(in oklch, var(--theme-accent) 22%, white), color-mix(in oklch, var(--theme-accent) 24%, #1b1117));
  --color-text-primary: light-dark(color-mix(in oklch, var(--theme-accent) 28%, #241820), color-mix(in oklch, var(--theme-accent) 18%, white));
  --color-text-muted: light-dark(color-mix(in oklch, var(--theme-accent) 42%, #686068), color-mix(in oklch, var(--theme-accent) 34%, #b8adb4));
  --color-accent-primary: light-dark(var(--theme-accent), color-mix(in oklch, var(--theme-accent) 72%, white));
  --color-accent-border: color-mix(in oklch, var(--color-accent-primary) 40%, transparent);
  --color-surface: light-dark(rgba(255 255 255 / 0.55), rgba(255 255 255 / 0.03));
  --color-surface-raised: light-dark(rgba(255 255 255 / 0.7), rgba(255 255 255 / 0.05));
  --color-success: light-dark(#3d8b5e, #62d68e);
  --color-warning: light-dark(#c08030, #e8b05c);
  --color-danger: light-dark(#c24858, #ed7a86);
  --color-info: light-dark(#3d7a8e, #5ec0d6);
  --focus-ring: 0 0 0 2px var(--color-accent-border);
}
""".strip()

_IFRAME_BASE_CSS = """
*, *::before, *::after { box-sizing: border-box; }
html, body {
  margin: 0;
  min-height: 100%;
  background: var(--color-bg-app);
  color: var(--color-text-primary);
  font-family: var(--font-settings);
  font-size: var(--text-md, 14px);
  line-height: var(--leading-normal, 1.45);
  scrollbar-color: var(--color-border-hover) var(--color-border);
  scrollbar-width: thin;
}
html[data-sk-surface="section"],
html[data-sk-surface="section"] body {
  background: transparent;
  min-height: 0;
  overflow: hidden;
}
button, input, textarea, select { font: inherit; color: inherit; }
""".strip()

_UI_COMPONENTS_CSS = """
.sk-stack { display: flex; flex-direction: column; gap: var(--space-3); }
.sk-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.sk-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-bg-panel);
  padding: var(--space-4);
}
.sk-card__title { margin: 0 0 var(--space-2); font-size: var(--text-lg); font-weight: var(--font-semibold, 650); }
.sk-field { display: flex; flex-direction: column; gap: var(--space-1); }
.sk-label { font-size: var(--text-sm); font-weight: 600; color: var(--color-text-primary); }
.sk-help { font-size: var(--text-xs); color: var(--color-text-muted); }
.sk-input, .sk-select, .sk-textarea {
  width: 100%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  padding: 7px 10px;
  font-size: var(--text-base);
}
.sk-input:focus-visible, .sk-select:focus-visible, .sk-textarea:focus-visible, .sk-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-color: var(--color-accent-primary);
}
.sk-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 6px 12px;
  border-radius: var(--radius-control);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  color: var(--color-text-primary);
  font-size: var(--text-base);
  font-weight: 600;
  cursor: pointer;
}
.sk-btn:hover:not(:disabled) { background: var(--color-control-hover); border-color: var(--color-border-hover); }
.sk-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.sk-btn--primary { background: var(--color-accent-primary); border-color: var(--color-accent-primary); color: #fff; }
.sk-btn--ghost { background: transparent; border-color: transparent; }
.sk-btn--danger { background: var(--color-danger); border-color: var(--color-danger); color: #fff; }
.sk-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
.sk-empty {
  padding: var(--space-4);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  color: var(--color-text-muted);
  text-align: center;
  font-size: var(--text-sm);
}
""".strip()

_HOST_BRIDGE_JS = r"""(function () {
  if (window.ShinsekaiHost) return;
  var HEX_RE = /^#[0-9a-f]{3}([0-9a-f]{3})?$/i;
  var VALID_LANGS = { zh_CN: "zh-CN", en: "en", ja: "ja" };
  var params = new URLSearchParams(window.location.search);
  var surface = String(params.get("surface") || "page").trim() || "page";
  document.documentElement.dataset.skSurface = surface;

  function normLang(raw) {
    var v = String(raw || "").trim().replace(/-/g, "_");
    var low = v.toLowerCase();
    if (low === "en" || low === "english") return "en";
    if (low === "ja" || low === "jp" || low === "japanese") return "ja";
    if (low === "zh" || low === "zh_cn" || v === "zh_CN") return "zh_CN";
    return "zh_CN";
  }

  var state = {
    theme: {
      accent: HEX_RE.test(params.get("themeAccent") || "") ? String(params.get("themeAccent")) : "#d4788e",
      colorScheme: String(params.get("colorScheme") || "light dark"),
      density: params.get("density") === "compact" ? "compact" : "normal",
    },
    language: normLang(params.get("lang")),
    context: {
      surface: surface,
      page: params.get("page") || "",
      slot: params.get("slot") || "",
      entityType: params.get("entityType") || "",
      entityId: params.get("entityId") || "",
    },
    messages: {},
  };

  function applyTheme(next) {
    if (!next || typeof next !== "object") return;
    if (typeof next.accent === "string" && HEX_RE.test(next.accent.trim())) {
      state.theme.accent = next.accent.trim().toLowerCase();
    }
    if (typeof next.colorScheme === "string" && next.colorScheme.trim()) {
      state.theme.colorScheme = next.colorScheme.trim();
    }
    if (next.density === "compact" || next.density === "normal") {
      state.theme.density = next.density;
    }
    var root = document.documentElement;
    root.style.setProperty("--theme-accent", state.theme.accent);
    root.style.colorScheme = state.theme.colorScheme;
    if (state.theme.density === "compact") root.dataset.density = "compact";
    else delete root.dataset.density;
  }

  function formatMsg(template, values) {
    if (!values || typeof values !== "object") return template;
    return template.replace(/\{([a-zA-Z0-9_]+)\}/g, function (_, k) {
      return k in values && values[k] != null ? String(values[k]) : "{" + k + "}";
    });
  }

  function translate(key, values) {
    var dict = state.messages[state.language] || state.messages.en || state.messages.zh_CN || {};
    var fallback = state.messages.en || state.messages.zh_CN || {};
    var raw = key in dict ? dict[key] : key in fallback ? fallback[key] : key;
    return formatMsg(String(raw), values);
  }

  function applyI18n(rootEl) {
    var target = rootEl || document;
    if (!target || !target.querySelectorAll) return;
    target.querySelectorAll("[data-sk-i18n]").forEach(function (el) {
      el.textContent = translate(el.getAttribute("data-sk-i18n"));
    });
    target.querySelectorAll("[data-sk-i18n-placeholder]").forEach(function (el) {
      el.setAttribute("placeholder", translate(el.getAttribute("data-sk-i18n-placeholder")));
    });
    target.querySelectorAll("[data-sk-i18n-title]").forEach(function (el) {
      el.setAttribute("title", translate(el.getAttribute("data-sk-i18n-title")));
    });
  }

  function applyLocale(rawLang) {
    state.language = normLang(rawLang);
    document.documentElement.lang = VALID_LANGS[state.language] || "zh-CN";
    applyI18n();
  }

  applyTheme(state.theme);
  applyLocale(state.language);

  var listeners = {
    theme: new Set(),
    locale: new Set(),
    context: new Set(),
    behaviorState: new Set(),
    behaviorEvent: new Set(),
    present: new Set(),
  };

  function subscribe(set, fn, opts) {
    if (typeof fn !== "function") return function () {};
    set.add(fn);
    if (opts && opts.immediate && set === listeners.theme) fn({ ...state.theme });
    if (opts && opts.immediate && set === listeners.locale) fn(state.language);
    if (opts && opts.immediate && set === listeners.context) fn({ ...state.context });
    return function () { set.delete(fn); };
  }

  function resolveParentOrigin() {
    if (document.referrer) {
      try { return new URL(document.referrer).origin; } catch (_) {}
    }
    return window.location.origin;
  }

  function postToParent(payload) {
    if (!window.parent || window.parent === window) return;
    var targetOrigin = resolveParentOrigin();
    if (!targetOrigin || targetOrigin === "null") return;
    window.parent.postMessage(payload, targetOrigin);
  }

  var lastHeight = 0;
  function reportHeight() {
    if (surface !== "section") return;
    var doc = document.documentElement;
    var body = document.body;
    var next = Math.ceil(Math.max(doc ? doc.scrollHeight : 0, body ? body.scrollHeight : 0));
    if (next > 0 && next !== lastHeight) {
      lastHeight = next;
      postToParent({ __shinsekai: "plugin-host", type: "resize", height: next });
    }
  }

  window.addEventListener("message", function (event) {
    if (window.parent && event.source !== window.parent) return;
    var data = event.data;
    if (!data || typeof data !== "object") return;
    if (data.__shinsekai === "plugin-host") {
      if (data.type === "theme.change") {
        applyTheme(data.theme);
        listeners.theme.forEach(function (fn) { fn({ ...state.theme }); });
      } else if (data.type === "locale.change") {
        applyLocale(data.language);
        listeners.locale.forEach(function (fn) { fn(state.language); });
      } else if (data.type === "context.change" && data.context && typeof data.context === "object") {
        state.context = { ...state.context, ...data.context };
        listeners.context.forEach(function (fn) { fn({ ...state.context }); });
      }
      return;
    }
    if (data.__shinsekai === "plugin-page") {
      if (data.type === "behavior.state") {
        listeners.behaviorState.forEach(function (fn) { fn(data.behavior ?? null); });
      } else if (data.type === "behavior.event") {
        listeners.behaviorEvent.forEach(function (fn) { fn(data); });
      } else if (data.type === "present") {
        listeners.present.forEach(function (fn) { fn(data); });
      }
    }
  });

  if (surface === "section") {
    var setupObserver = function () {
      reportHeight();
      if (typeof ResizeObserver === "function" && document.body) {
        new ResizeObserver(function () { window.requestAnimationFrame(reportHeight); }).observe(document.body);
      }
    };
    if (document.readyState === "loading") window.addEventListener("DOMContentLoaded", setupObserver);
    else setupObserver();
  }

  window.ShinsekaiHost = {
    getTheme: function () { return { ...state.theme }; },
    getLanguage: function () { return state.language; },
    getContext: function () { return { ...state.context }; },
    registerMessages: function (dict) {
      if (!dict || typeof dict !== "object") return;
      Object.keys(dict).forEach(function (langKey) {
        var norm = normLang(langKey);
        if (dict[langKey] && typeof dict[langKey] === "object") {
          state.messages[norm] = { ...(state.messages[norm] || {}), ...dict[langKey] };
        }
      });
      applyI18n();
      reportHeight();
    },
    t: translate,
    applyI18n: applyI18n,
    onThemeChange: function (fn, opts) { return subscribe(listeners.theme, fn, opts); },
    onLocaleChange: function (fn, opts) { return subscribe(listeners.locale, fn, opts); },
    onContextChange: function (fn, opts) { return subscribe(listeners.context, fn, opts); },
    onBehaviorState: function (fn) { return subscribe(listeners.behaviorState, fn); },
    onBehaviorEvent: function (fn) { return subscribe(listeners.behaviorEvent, fn); },
    onPresent: function (fn) { return subscribe(listeners.present, fn); },
    reportHeight: reportHeight,
    requestRefresh: function (targets) {
      postToParent({
        __shinsekai: "plugin-host",
        type: "refresh",
        targets: Array.isArray(targets) ? targets : [],
      });
    },
  };
})();
"""


def render_sdk_theme_css(project_root: Path | None = None) -> bytes:
    """Return host CSS custom properties and baseline styles for plugin iframes."""
    root = resolve_regular_path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    theme_dir = root / "frontend" / "src" / "shared" / "theme"
    chunks: list[str] = []
    for filename in ("tokens.css", "color.css", "typography.css"):
        candidate = theme_dir / filename
        if candidate.is_file():
            chunks.append(candidate.read_text(encoding="utf-8").strip())
    if not chunks:
        chunks.append(_FALLBACK_THEME_CSS)
    chunks.append(_IFRAME_BASE_CSS)
    return ("\n\n".join(chunks) + "\n").encode("utf-8")


def render_sdk_ui_css() -> bytes:
    """Return optional host-matched `.sk-*` primitive classes for plugin pages."""
    return (_UI_COMPONENTS_CSS + "\n").encode("utf-8")


def render_sdk_host_bridge_js() -> bytes:
    """Return the browser bridge script synced with host theme, locale, context, and height."""
    return _HOST_BRIDGE_JS.encode("utf-8")


def resolve_sdk_asset(
    path: str,
    *,
    project_root: Path | None = None,
) -> tuple[str, bytes] | None:
    """Return ``(content_type, payload)`` for built-in SDK static endpoints, or None."""
    cleaned = str(path or "").split("?", 1)[0]
    if cleaned == SDK_THEME_CSS_PATH:
        return ("text/css; charset=utf-8", render_sdk_theme_css(project_root=project_root))
    if cleaned == SDK_UI_CSS_PATH:
        return ("text/css; charset=utf-8", render_sdk_ui_css())
    if cleaned == SDK_HOST_BRIDGE_JS_PATH:
        return ("application/javascript; charset=utf-8", render_sdk_host_bridge_js())
    return None


def inject_plugin_sdk_into_html(html_bytes: bytes) -> bytes:
    """Inject host theme CSS and bridge script into a plugin HTML document once."""
    text = html_bytes.decode("utf-8", errors="replace")
    if SDK_HOST_BRIDGE_JS_PATH in text:
        return html_bytes
    snippet = (
        f'<link rel="stylesheet" href="{SDK_THEME_CSS_PATH}">'
        f'<link rel="stylesheet" href="{SDK_UI_CSS_PATH}">'
        f'<script src="{SDK_HOST_BRIDGE_JS_PATH}"></script>'
    )
    if _HEAD_OPEN_RE.search(text):
        updated = _HEAD_OPEN_RE.sub(rf"\1\n  {snippet}", text, count=1)
    else:
        updated = f"{snippet}\n{text}"
    return updated.encode("utf-8")
