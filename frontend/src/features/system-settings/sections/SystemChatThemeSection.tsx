import { Palette } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { chatThemeDisplayName } from "../../../shared/theme/chatTheme";
import { Button, Select, type PageSectionProps } from "../../../shared/ui";
import type { SystemSettingsPageContext } from "../systemSettingsContext";

export function SystemChatThemeSection({ ctx }: PageSectionProps<SystemSettingsPageContext>) {
  const { language, t } = useI18n();

  return (
    <section className="section system-chat-theme page-section-anchor" id="system-chat-theme">
      <div className="section__header">
        <h2 className="section__title">{t("chat.theme.title")}</h2>
        <div className="section__actions">
          <Button icon={<Palette aria-hidden className="button__icon" />} onClick={ctx.openChatThemes}>
            {t("chat.theme.open")}
          </Button>
        </div>
      </div>
      <div className="field-row">
        <span className="field-row__label">
          <Palette aria-hidden className="system-chat-theme__icon" />
          <label className="field-row__label-text" htmlFor="chat_ui_theme_id">
            {t("chat.theme.title")}
          </label>
        </span>
        <span className="field-row__control">
          <Select
            aria-describedby="chat_ui_theme_id-help"
            disabled={ctx.savePending || ctx.chatThemesLoading || ctx.themeOptions.length === 0}
            id="chat_ui_theme_id"
            onChange={(event) => ctx.setDraft({ ...ctx.draft, chat_ui_theme_id: event.target.value })}
            value={ctx.selectedThemeId}
          >
            {ctx.themeOptions.map((theme) => (
              <option key={theme.id} value={theme.id}>
                {chatThemeDisplayName(theme, language)}
                {theme.source === "builtin"
                  ? ` · ${t("chat.theme.sourceBuiltin")}`
                  : ` · ${t("chat.theme.sourceUser")}`}
              </option>
            ))}
          </Select>
          <span className="field-row__help" id="chat_ui_theme_id-help">
            {t("ops.system.chatThemeHelp")}
          </span>
          {ctx.chatThemesLoading ? <span className="field-row__help">{t("system.loading")}</span> : null}
          {!ctx.chatThemesLoading && ctx.themeOptions.length === 0 ? (
            <span className="field-row__help">{t("chat.theme.empty")}</span>
          ) : null}
          {ctx.chatThemesIsError ? (
            <span className="field-error">
              {ctx.chatThemesError instanceof Error ? ctx.chatThemesError.message : t("chat.theme.error.apply")}
            </span>
          ) : null}
        </span>
      </div>
    </section>
  );
}
