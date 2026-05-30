import { NavLink } from "react-router-dom";
import { Brush, FileImage, Gamepad2, LayoutTemplate, Plug, Settings, SlidersHorizontal, Wrench } from "lucide-react";
import type { MessageKey } from "../../shared/i18n";
import { useI18n } from "../../shared/i18n";

const links = [
  { icon: Settings, labelKey: "nav.api", to: "/settings/api" },
  { icon: Gamepad2, labelKey: "nav.character", to: "/settings/characters" },
  { icon: FileImage, labelKey: "nav.background", to: "/settings/backgrounds" },
  { icon: LayoutTemplate, labelKey: "nav.template", to: "/settings/templates" },
  { icon: Plug, labelKey: "nav.plugins", to: "/settings/plugins" },
  { icon: SlidersHorizontal, labelKey: "nav.system", to: "/settings/system" },
] satisfies Array<{ icon: typeof Settings; labelKey: MessageKey; to: string }>;

type SidebarNavProps = {
  toolsOpen: boolean;
  onToolsToggle: () => void;
};

export function SidebarNav({ onToolsToggle, toolsOpen }: SidebarNavProps) {
  const { t } = useI18n();

  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div aria-hidden className="sidebar__brand-mark">
          <Brush className="sidebar__icon" />
        </div>
        <div className="sidebar__brand-text">
          <p className="sidebar__brand-title">{t("app.title")}</p>
          <p className="sidebar__brand-subtitle">{t("app.brandSubtitle")}</p>
        </div>
      </div>
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
