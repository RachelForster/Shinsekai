import { NavLink } from "react-router-dom";
import {
  Brush,
  FileImage,
  Gamepad2,
  Github,
  LayoutTemplate,
  Plug,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Star,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { openExternal } from "../../entities/files/repository";
import type { MessageKey } from "../../shared/i18n";
import { useI18n } from "../../shared/i18n";
import { useAppUpdateInfo } from "./useAppUpdateInfo";

const GITHUB_REPO_URL = "https://github.com/RachelForster/Shinsekai";
const GITHUB_REPO_API_URL = "https://api.github.com/repos/RachelForster/Shinsekai";

const links = [
  { icon: Settings, labelKey: "nav.api", to: "/settings/api" },
  { icon: Gamepad2, labelKey: "nav.character", to: "/settings/characters" },
  { icon: FileImage, labelKey: "nav.background", to: "/settings/backgrounds" },
  { icon: LayoutTemplate, labelKey: "nav.template", to: "/settings/templates" },
  { icon: Plug, labelKey: "nav.plugins", to: "/settings/plugins" },
  { icon: ScrollText, labelKey: "nav.logs", to: "/settings/logs" },
  { icon: SlidersHorizontal, labelKey: "nav.system", to: "/settings/system" },
] satisfies Array<{ icon: typeof Settings; labelKey: MessageKey; to: string }>;

type SidebarNavProps = {
  toolsOpen: boolean;
  onToolsToggle: () => void;
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

export function SidebarNav({ onToolsToggle, toolsOpen }: SidebarNavProps) {
  const { t } = useI18n();
  const versionQuery = useAppUpdateInfo();
  const rawVersion = versionQuery.data?.version?.trim() ?? "";
  const version = rawVersion ? (rawVersion.toLowerCase().startsWith("v") ? rawVersion : `v${rawVersion}`) : "";
  const stars = useGitHubStars();
  const starLabel = stars == null ? t("nav.githubStarsLoading") : t("nav.githubStars", { count: formatStars(stars) });

  return (
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
        {links.map((link) => {
          const Icon = link.icon;
          return (
            <NavLink className="sidebar__link" key={link.to} title={t(link.labelKey)} to={link.to}>
              <Icon aria-hidden className="sidebar__icon" />
              <span className="sidebar__link-label">{t(link.labelKey)}</span>
            </NavLink>
          );
        })}
      </nav>
      <div className="sidebar__spacer" />
      <nav aria-label={t("nav.secondary")} className="sidebar__nav sidebar__nav--secondary">
        <button
          aria-pressed={toolsOpen}
          className="sidebar__link sidebar__link--button"
          onClick={onToolsToggle}
          title={t("nav.tools")}
          type="button"
        >
          <Wrench aria-hidden className="sidebar__icon" />
          <span className="sidebar__link-label">{t("nav.tools")}</span>
        </button>
      </nav>
    </aside>
  );
}
