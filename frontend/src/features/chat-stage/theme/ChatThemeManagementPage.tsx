import { ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { ChatThemeManager } from "./ChatThemePicker";
import "./chat-theme-management-page.css";

export function ChatThemeManagementPage() {
  const navigate = useNavigate();
  const { t } = useI18n();

  return (
    <div className="page chat-theme-management-page">
      <header className="page__header chat-theme-management-page__header">
        <div className="chat-theme-management-page__heading">
          <Button
            className="chat-theme-management-page__back"
            icon={<ArrowLeft aria-hidden className="button__icon" />}
            onClick={() => navigate("/settings/system")}
            variant="ghost"
          >
            {t("chat.theme.backToSettings")}
          </Button>
          <div>
            <h1 className="page__title">{t("chat.theme.title")}</h1>
            <p className="chat-theme-management-page__description">{t("chat.theme.pageDescription")}</p>
          </div>
        </div>
      </header>
      <section className="section chat-theme-management-page__content">
        <ChatThemeManager />
      </section>
    </div>
  );
}
