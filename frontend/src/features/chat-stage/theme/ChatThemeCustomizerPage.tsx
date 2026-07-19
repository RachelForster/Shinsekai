import { ArrowLeft, Redo2, RotateCcw, Save, Undo2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useI18n } from "../../../shared/i18n";
import { chatThemeDisplayName } from "../../../shared/theme/chatTheme";
import { Button, Select } from "../../../shared/ui";
import { ChatThemeEditor } from "./ChatThemeEditor";
import { ChatThemePreview, type ChatThemePreviewMode } from "./ChatThemePreview";
import "./chat-theme-customizer-page.css";
import { useChatThemeCustomizer } from "./useChatThemeCustomizer";

export function ChatThemeCustomizerPage() {
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const [previewMode, setPreviewMode] = useState<ChatThemePreviewMode>("dialog");
  const customizer = useChatThemeCustomizer();

  return (
    <div className="page chat-theme-customizer-page">
      <header className="page__header chat-theme-customizer-page__header">
        <div className="chat-theme-customizer-page__heading">
          <Button
            icon={<ArrowLeft aria-hidden className="button__icon" />}
            onClick={() => navigate("/settings/system/chat-themes")}
            variant="ghost"
          >
            {t("chat.theme.customizer.back")}
          </Button>
          <div>
            <h1 className="page__title">{t("chat.theme.customizer.title")}</h1>
            <p>{t("chat.theme.customizer.description")}</p>
          </div>
        </div>
        <div className="chat-theme-customizer-page__actions">
          <Button
            disabled={!customizer.canUndo || customizer.saving}
            icon={<Undo2 aria-hidden className="button__icon" />}
            onClick={customizer.undo}
          >
            {t("common.undo")}
          </Button>
          <Button
            disabled={!customizer.canRedo || customizer.saving}
            icon={<Redo2 aria-hidden className="button__icon" />}
            onClick={customizer.redo}
          >
            {t("common.redo")}
          </Button>
          <Button
            disabled={!customizer.sourceReady || !customizer.dirty || customizer.saving}
            icon={<RotateCcw aria-hidden className="button__icon" />}
            onClick={customizer.reset}
          >
            {t("chat.theme.customizer.reset")}
          </Button>
          <Button
            disabled={
              !customizer.sourceReady ||
              !customizer.draft ||
              customizer.invalid ||
              !customizer.dirty ||
              customizer.loading ||
              customizer.saving
            }
            icon={<Save aria-hidden className="button__icon" />}
            loading={customizer.saving}
            onClick={() => void customizer.save()}
            variant="primary"
          >
            {t("common.saveApply")}
          </Button>
        </div>
      </header>

      <section className="chat-theme-customizer__source-bar">
        <label>
          <span>{t("chat.theme.customizer.baseTheme")}</span>
          <Select
            aria-label={t("chat.theme.customizer.baseTheme")}
            disabled={customizer.saving}
            onChange={(event) => customizer.setSourceId(event.target.value)}
            value={customizer.sourceId}
          >
            {customizer.themes.map((item) => (
              <option key={item.id} value={item.id}>
                {chatThemeDisplayName(item, language)} ·{" "}
                {t(item.source === "builtin" ? "chat.theme.sourceBuiltin" : "chat.theme.sourceUser")}
              </option>
            ))}
          </Select>
        </label>
        <p>{t(customizer.isNewTheme ? "chat.theme.customizer.cloneHint" : "chat.theme.customizer.editHint")}</p>
      </section>

      {customizer.loadError ? <div className="chat-theme-customizer__error">{customizer.loadError}</div> : null}
      {customizer.loading || !customizer.draft ? (
        <div className="chat-theme-customizer__loading">{t("chat.theme.customizer.loading")}</div>
      ) : (
        <div className="chat-theme-customizer__workspace">
          <ChatThemeEditor
            draft={customizer.draft}
            duplicateId={customizer.duplicateId}
            idError={customizer.idError}
            isNewTheme={customizer.isNewTheme}
            nameError={customizer.nameError}
            onPatchManifest={customizer.patchManifest}
            onPatchToken={customizer.patchToken}
            onResetSection={customizer.resetSection}
          />
          <ChatThemePreview
            assetThemeId={customizer.assetThemeId}
            manifest={customizer.draft}
            mode={previewMode}
            onModeChange={setPreviewMode}
          />
        </div>
      )}
    </div>
  );
}
