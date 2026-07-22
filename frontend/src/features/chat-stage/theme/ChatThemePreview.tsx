import { Mic, Send, SlidersHorizontal } from "lucide-react";
import { useMemo, type CSSProperties } from "react";

import { useI18n } from "../../../shared/i18n";
import { resolveChatTheme, type ChatThemeManifest } from "../../../shared/theme/chatTheme";
import { Button, SegmentedTabs, ThemeBackground, ThemeFrame } from "../../../shared/ui";
import { DialogLayer, OptionsLayer } from "../components/StageLayers";
import "../chat-stage.css";
import { chatThemeAssetUrl } from "./ChatThemeProvider";

export type ChatThemePreviewMode = "dialog" | "options";

function PreviewInput({ layout }: { layout: "default" | "pill" }) {
  const { t } = useI18n();
  const pill = layout === "pill";
  return (
    <div className="input-layer" data-layout={layout} data-visible="true">
      <ThemeBackground prefix="chat-input" />
      <ThemeFrame prefix="chat-input" />
      {pill ? (
        <button aria-label="Mic" className="input-layer__press icon-button" type="button">
          <Mic aria-hidden className="icon-button__icon" />
        </button>
      ) : null}
      <div className="input-layer__field">
        <input
          className={`input-layer__input${pill ? " input-layer__input--single" : ""}`}
          placeholder={t("chat.input.placeholder")}
          readOnly
        />
        {!pill ? (
          <Button
            backgroundLayer={<ThemeBackground prefix="chat-send" />}
            className="input-layer__send"
            icon={<Send aria-hidden className="button__icon" />}
            variant="primary"
          >
            {t("chat.input.send")}
          </Button>
        ) : null}
      </div>
      {pill ? (
        <div className="input-layer__pill-actions">
          <button aria-label={t("chat.input.send")} className="input-layer__quick-submit icon-button" type="button">
            <ThemeBackground prefix="chat-send" />
            <Send aria-hidden className="icon-button__icon" />
          </button>
        </div>
      ) : (
        <div aria-hidden className="input-layer__voice-stack">
          <button className="input-layer__voice-button button" type="button">
            <Mic aria-hidden className="button__icon" />
          </button>
          <button className="input-layer__voice-button button" type="button">
            <SlidersHorizontal aria-hidden className="button__icon" />
          </button>
        </div>
      )}
    </div>
  );
}

export function ChatThemePreview({
  assetThemeId,
  manifest,
  mode,
  onModeChange,
}: {
  assetThemeId: string;
  manifest: ChatThemeManifest;
  mode: ChatThemePreviewMode;
  onModeChange: (mode: ChatThemePreviewMode) => void;
}) {
  const { t } = useI18n();
  const resolved = useMemo(
    () => resolveChatTheme(manifest, (rel) => chatThemeAssetUrl(assetThemeId, rel)),
    [assetThemeId, manifest],
  );
  const inputLayout = resolved.style["--chat-input-layout"] === "pill" ? "pill" : "default";

  return (
    <aside className="chat-theme-customizer__preview-panel">
      <div className="chat-theme-customizer__preview-header">
        <div>
          <strong>{t("chat.theme.customizer.preview")}</strong>
          <span>{t("chat.theme.customizer.previewHint")}</span>
        </div>
        <SegmentedTabs
          ariaLabel={t("chat.theme.customizer.preview")}
          items={[
            { id: "dialog", label: t("chat.theme.customizer.previewDialog") },
            { id: "options", label: t("chat.theme.customizer.previewOptions") },
          ]}
          onChange={onModeChange}
          value={mode}
          variant="pills"
        />
      </div>
      <div className="chat-theme-customizer__preview-stage chat-stage" style={resolved.style as CSSProperties}>
        <div aria-hidden className="top-stage-tools" data-visible="true">
          <ThemeBackground prefix="chat-toolbar" />
          <ThemeFrame prefix="chat-toolbar" />
          <div className="top-stage-tools__status">
            <span className="top-stage-tools__transport">Theme</span>
            <span className="top-stage-tools__state">UI</span>
          </div>
        </div>
        <div aria-hidden className="chat-theme-customizer__preview-sky">
          <span className="chat-theme-customizer__preview-moon" />
          <span className="chat-theme-customizer__preview-horizon" />
          <span className="chat-theme-customizer__preview-character" />
        </div>
        <div className="dialog-stack">
          {mode === "dialog" ? (
            <DialogLayer
              canAdvance
              characterName={t("chat.theme.customizer.previewName")}
              hidden={false}
              onAdvance={() => undefined}
              text={t("chat.theme.customizer.previewText")}
              typing={false}
            />
          ) : (
            <OptionsLayer
              hidden={false}
              onSelect={() => undefined}
              options={[
                t("chat.theme.customizer.previewOptionOne"),
                t("chat.theme.customizer.previewOptionTwo"),
                t("chat.theme.customizer.previewOptionThree"),
              ]}
            />
          )}
        </div>
        <PreviewInput layout={inputLayout} />
      </div>
    </aside>
  );
}
