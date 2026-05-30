import { Settings } from "lucide-react";
import { Link } from "react-router-dom";

import { useI18n } from "../../shared/i18n";

export function TopBar() {
  const { t } = useI18n();

  return (
    <header className="topbar">
      <div>
        <p className="topbar__title">{t("app.title")}</p>
      </div>
      <div className="topbar__actions">
        <Link
          aria-label={t("nav.system")}
          className="topbar__icon-button"
          title={t("nav.system")}
          to="/settings/system"
        >
          <Settings aria-hidden />
        </Link>
      </div>
    </header>
  );
}
