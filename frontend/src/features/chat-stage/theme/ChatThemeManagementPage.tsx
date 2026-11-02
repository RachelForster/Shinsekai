import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Paintbrush } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { chatThemeQueryKey } from "../../../entities/chat/repository";
import { configQueryKey } from "../../../entities/config/repository";
import type { AppConfig } from "../../../entities/config/types";
import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { ChatThemeManager } from "./ChatThemePicker";
import "./chat-theme-management-page.css";

export function ChatThemeManagementPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { t } = useI18n();

  const handleActiveThemeChange = (id: string | null) => {
    queryClient.setQueryData<AppConfig>(configQueryKey, (current) =>
      current
        ? {
            ...current,
            system_config: {
              ...current.system_config,
              chat_ui_theme_id: id ?? "",
            },
          }
        : current,
    );
    void queryClient.invalidateQueries({ queryKey: configQueryKey });
  };

  const handleThemesChange = () => {
    void queryClient.invalidateQueries({ queryKey: chatThemeQueryKey });
  };

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
        <Button
          icon={<Paintbrush aria-hidden className="button__icon" />}
          onClick={() => navigate("/settings/system/chat-themes/customize")}
          variant="primary"
        >
          {t("chat.theme.customize")}
        </Button>
      </header>
      <section className="section chat-theme-management-page__content">
        <ChatThemeManager onActiveThemeChange={handleActiveThemeChange} onThemesChange={handleThemesChange} />
      </section>
    </div>
  );
}
