import { NavLink, useLocation } from "react-router-dom";
import {
  Bot,
  Brush,
  FileImage,
  Gamepad2,
  Github,
  LayoutTemplate,
  MessageCircle,
  Plug,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Star,
} from "lucide-react";
import { useEffect, useState } from "react";
import { openExternal } from "../../entities/files/repository";
import type { FrontendLanguage, MessageKey } from "../../shared/i18n";
import { useI18n } from "../../shared/i18n";
import { useAppUpdateInfo } from "./useAppUpdateInfo";

const GITHUB_REPO_URL = "https://github.com/RachelForster/Shinsekai";
const GITHUB_REPO_API_URL = "https://api.github.com/repos/RachelForster/Shinsekai";

type SidebarLink = {
  icon: typeof Settings;
  label?: Record<FrontendLanguage, string>;
  labelKey?: MessageKey;
  to: string;
};

const settingsLinks = [
  { icon: Sparkles, label: { en: "Guide", ja: "ガイド", zh_CN: "新手引导" }, to: "/settings/onboarding" },
  { icon: Settings, labelKey: "nav.api", to: "/settings/api" },
  { icon: Gamepad2, labelKey: "nav.character", to: "/settings/characters" },
  { icon: FileImage, labelKey: "nav.background", to: "/settings/backgrounds" },
  { icon: Sparkles, labelKey: "nav.effects", to: "/settings/effects" },
  { icon: LayoutTemplate, labelKey: "nav.template", to: "/settings/templates" },
] satisfies SidebarLink[];

const extensionLinks = [{ icon: Plug, labelKey: "nav.plugins", to: "/settings/plugins" }] satisfies Array<{
  icon: typeof Settings;
  labelKey: MessageKey;
  to: string;
}>;

const maintenanceLinks = [
  { icon: ScrollText, labelKey: "nav.logs", to: "/settings/logs" },
  { icon: SlidersHorizontal, labelKey: "nav.system", to: "/settings/system" },
] satisfies SidebarLink[];

type SidebarNavProps = {
  assistantOpen: boolean;
  onAssistantToggle: () => void;
};

function formatStars(count: number) {
  return new Intl.NumberFormat(undefined, {
    compactDisplay: "short",
    maximumFractionDigits: count >= 1000 ? 1 : 0,
    notation: "compact",
  }).format(count);
}

function useGitHubStars() {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    if (typeof fetch !== "function") {
      return;
    }

    const controller = new AbortController();
    fetch(GITHUB_REPO_API_URL, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: unknown) => {
        if (data && typeof data === "object" && "stargazers_count" in data) {
          const value = Number(data.stargazers_count);
          if (Number.isFinite(value)) {
            setStars(value);
          }
        }
      })
      .catch(() => {
        // Keep the repository link visible even when offline or rate-limited.
      });

    return () => controller.abort();
  }, []);

  return stars;
}

function sidebarLinkLabel(link: SidebarLink, language: FrontendLanguage, t: (key: MessageKey) => string) {
  if (link.labelKey) {
    return t(link.labelKey);
  }
  return link.label?.[language] ?? link.label?.en ?? "";
}

const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "checkbox",
  "color",
  "file",
  "hidden",
  "image",
  "radio",
  "range",
  "reset",
  "submit",
]);

/** Return true only when focusing `el` is expected to open an on-screen virtual keyboard. */
function opensVirtualKeyboard(el: Element | null): boolean {
  if (!el || !(el instanceof HTMLElement)) {
    return false;
  }
  if (el.getAttribute("inputmode") === "none") {
    return false;
  }
  if (el instanceof HTMLInputElement) {
    if (el.readOnly || el.disabled) {
      return false;
    }
    const inputType = (el.getAttribute("type") || el.type || "text").toLowerCase();
    return !NON_TEXT_INPUT_TYPES.has(inputType);
  }
  if (el instanceof HTMLTextAreaElement) {
    return !el.readOnly && !el.disabled;
  }
  return Boolean(el.isContentEditable || el.getAttribute("contenteditable") === "true");
}

export function SidebarNav({ onAssistantToggle, assistantOpen }: SidebarNavProps) {
  const { language, t } = useI18n();
  const location = useLocation();
  const [keyboardOpen, setKeyboardOpen] = useState(false);

  useEffect(() => {
    if (typeof document === "undefined" || typeof window === "undefined") {
      return;
    }
    const handleFocusIn = (event: FocusEvent) => {
      if (window.innerWidth > 760) {
        setKeyboardOpen(false);
        return;
      }
      const target = (event.target as Element | null) ?? document.activeElement;
      setKeyboardOpen(opensVirtualKeyboard(target));
    };

    const handleFocusOut = (event: FocusEvent) => {
      if (window.innerWidth > 760) {
        setKeyboardOpen(false);
        return;
      }
      const nextTarget =
        (event.relatedTarget as Element | null) ??
        (document.activeElement !== event.target ? document.activeElement : null);
      setKeyboardOpen(opensVirtualKeyboard(nextTarget));
    };

    const handleResize = () => {
      setKeyboardOpen(window.innerWidth <= 760 && opensVirtualKeyboard(document.activeElement));
    };

    document.addEventListener("focusin", handleFocusIn);
    document.addEventListener("focusout", handleFocusOut);
    window.addEventListener("resize", handleResize);
    return () => {
      document.removeEventListener("focusin", handleFocusIn);
      document.removeEventListener("focusout", handleFocusOut);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  const versionQuery = useAppUpdateInfo();
  const rawVersion = versionQuery.data?.version?.trim() ?? "";
  const version = rawVersion ? (rawVersion.toLowerCase().startsWith("v") ? rawVersion : `v${rawVersion}`) : "";
  const stars = useGitHubStars();
  const starLabel = stars == null ? t("nav.githubStarsLoading") : t("nav.githubStars", { count: formatStars(stars) });

  const chatManageActive =
    location.pathname.startsWith("/settings/templates") ||
    location.pathname.startsWith("/settings/launch") ||
    location.pathname.startsWith("/settings/stories");
  const decorateActive =
    location.pathname.startsWith("/settings/backgrounds") || location.pathname.startsWith("/settings/effects");
  const systemActive =
    location.pathname.startsWith("/settings/system") ||
    location.pathname.startsWith("/settings/logs") ||
    location.pathname.startsWith("/settings/plugins") ||
    location.pathname.startsWith("/settings/tools") ||
    location.pathname.startsWith("/settings/music-cover");

  return (
    <>
      <aside className="sidebar">
        <div className="sidebar__brand">
          <div aria-hidden className="sidebar__brand-mark">
            <Brush className="sidebar__icon" />
          </div>
          <div className="sidebar__brand-text">
            <p className="sidebar__brand-title">{t("app.title")}</p>
            <p className="sidebar__brand-subtitle">{t("app.brandSubtitle")}</p>
            {version ? <p className="sidebar__brand-version">{version}</p> : null}
          </div>
        </div>
        <button
          className="sidebar__github"
          onClick={() => openExternal(GITHUB_REPO_URL)}
          title={t("nav.githubRepo")}
          type="button"
        >
          <Github aria-hidden className="sidebar__github-icon" />
          <span className="sidebar__github-body">
            <span className="sidebar__github-label">{t("nav.githubRepo")}</span>
            <span className="sidebar__github-stars">
              <Star aria-hidden className="sidebar__github-star-icon" />
              {starLabel}
            </span>
          </span>
        </button>
        <nav aria-label={t("nav.settingsCenter")} className="sidebar__nav">
          <div className="sidebar__section-label">{t("nav.groupSettings")}</div>
          {settingsLinks.map((link) => {
            const Icon = link.icon;
            const label = sidebarLinkLabel(link, language, t);
            return (
              <NavLink className="sidebar__link" key={link.to} title={label} to={link.to}>
                <Icon aria-hidden className="sidebar__icon" />
                <span className="sidebar__link-label">{label}</span>
              </NavLink>
            );
          })}
          <div className="sidebar__section-label">{t("nav.groupExtensions")}</div>
          {extensionLinks.map((link) => {
            const Icon = link.icon;
            const label = sidebarLinkLabel(link, language, t);
            return (
              <NavLink className="sidebar__link" key={link.to} title={label} to={link.to}>
                <Icon aria-hidden className="sidebar__icon" />
                <span className="sidebar__link-label">{label}</span>
              </NavLink>
            );
          })}
          <div className="sidebar__section-label">{t("nav.groupMaintenance")}</div>
          {maintenanceLinks.map((link) => {
            const Icon = link.icon;
            const label = sidebarLinkLabel(link, language, t);
            return (
              <NavLink className="sidebar__link" key={link.to} title={label} to={link.to}>
                <Icon aria-hidden className="sidebar__icon" />
                <span className="sidebar__link-label">{label}</span>
              </NavLink>
            );
          })}
        </nav>
        <div className="sidebar__spacer" />
        <nav aria-label={t("nav.secondary")} className="sidebar__nav sidebar__nav--secondary">
          <button
            aria-pressed={assistantOpen}
            className="sidebar__link sidebar__link--button"
            onClick={onAssistantToggle}
            title={t("nav.assistant")}
            type="button"
          >
            <Bot aria-hidden className="sidebar__icon" />
            <span className="sidebar__link-label">{t("nav.assistant")}</span>
          </button>
        </nav>
      </aside>
      <nav
        aria-label="移动端底部导航"
        className="mobile-bottom-nav"
        data-keyboard-open={keyboardOpen ? "true" : "false"}
      >
        <NavLink
          className={({ isActive }) =>
            ["mobile-bottom-nav__item", isActive || chatManageActive ? "active" : ""].filter(Boolean).join(" ")
          }
          to="/settings/templates"
        >
          <span aria-hidden className="mobile-bottom-nav__indicator">
            <MessageCircle aria-hidden className="mobile-bottom-nav__icon" />
          </span>
          <span>聊天管理</span>
        </NavLink>
        <NavLink className="mobile-bottom-nav__item" to="/settings/characters">
          <span aria-hidden className="mobile-bottom-nav__indicator">
            <Gamepad2 aria-hidden className="mobile-bottom-nav__icon" />
          </span>
          <span>角色</span>
        </NavLink>
        <NavLink className="mobile-bottom-nav__item" to="/settings/api">
          <span aria-hidden className="mobile-bottom-nav__indicator">
            <Settings aria-hidden className="mobile-bottom-nav__icon" />
          </span>
          <span>API</span>
        </NavLink>
        <NavLink
          className={({ isActive }) =>
            ["mobile-bottom-nav__item", isActive || decorateActive ? "active" : ""].filter(Boolean).join(" ")
          }
          to="/settings/backgrounds"
        >
          <span aria-hidden className="mobile-bottom-nav__indicator">
            <FileImage aria-hidden className="mobile-bottom-nav__icon" />
          </span>
          <span>装扮</span>
        </NavLink>
        <NavLink
          className={({ isActive }) =>
            ["mobile-bottom-nav__item", isActive || systemActive ? "active" : ""].filter(Boolean).join(" ")
          }
          to="/settings/system"
        >
          <span aria-hidden className="mobile-bottom-nav__indicator">
            <SlidersHorizontal aria-hidden className="mobile-bottom-nav__icon" />
          </span>
          <span>系统</span>
        </NavLink>
      </nav>
    </>
  );
}
