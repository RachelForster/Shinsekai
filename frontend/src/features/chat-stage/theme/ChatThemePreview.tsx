import {
  CheckCircle2,
  FileText,
  History,
  Lock,
  Play,
  Search,
  Send,
  Settings,
  SlidersHorizontal,
  TriangleAlert,
  Mic,
} from "lucide-react";
import { useMemo, type CSSProperties } from "react";

import { useI18n } from "../../../shared/i18n";
import { diagnoseChatTheme } from "../../../shared/theme/chatThemeDiagnostics";
import {
  resolveChatTheme,
  type ChatThemeAsset,
  type ChatThemeManifest,
} from "../../../shared/theme/chatTheme";
import { Button, SegmentedTabs, ThemeFrame } from "../../../shared/ui";
import { DialogLayer, OptionsLayer } from "../components/StageLayers";
import "../chat-stage.css";
import { chatThemeAssetUrl } from "./ChatThemeProvider";

export type ChatThemePreviewMode = "dialog" | "logs" | "options" | "toolbar";
export type ChatThemePreviewState = "active" | "default" | "hover";
export type ChatThemePreviewViewport = "compact" | "desktop" | "mobile";

function PreviewInput({ layout }: { layout: "default" | "pill" }) {
  const { t } = useI18n();
  const pill = layout === "pill";
  return (
    <div className="input-layer" data-layout={layout} data-visible="true">
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
          <Button className="input-layer__send" icon={<Send aria-hidden className="button__icon" />} variant="primary">
            {t("chat.input.send")}
          </Button>
        ) : null}
      </div>
      {pill ? (
        <div className="input-layer__pill-actions">
          <button aria-label={t("chat.input.send")} className="input-layer__quick-submit icon-button" type="button">
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

function PreviewToolbar() {
  const { t } = useI18n();
  return (
    <div className="chat-theme-preview__toolbar dialog-stage-controls" data-locked="true">
      <div className="dialog-stage-controls__surface">
        <ThemeFrame prefix="chat-toolbar" />
        <div className="dialog-stage-controls__rail" role="toolbar">
          <Button className="dialog-stage-controls__button" icon={<Lock aria-hidden className="button__icon" />}>
            {t("chat.actionBar.lock")}
          </Button>
          <Button className="dialog-stage-controls__button" icon={<History aria-hidden className="button__icon" />}>
            {t("chat.actionBar.history")}
          </Button>
          <Button className="dialog-stage-controls__button" icon={<Play aria-hidden className="button__icon" />}>
            {t("chat.actionBar.auto")}
          </Button>
          <Button className="dialog-stage-controls__button" icon={<Settings aria-hidden className="button__icon" />}>
            {t("chat.input.settings")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function PreviewLogs() {
  const { t } = useI18n();
  const lines = [
    t("chat.theme.customizer.previewLogLine1"),
    t("chat.theme.customizer.previewLogLine2"),
    t("chat.theme.customizer.previewLogLine3"),
  ];
  return (
    <div className="chat-theme-preview__logs">
      <section className="chat-theme-preview__logs-toolbar">
        <ThemeFrame prefix="logs-toolbar" fallbackPrefix="logs-panel" />
        <Search aria-hidden />
        <span>{t("chat.theme.customizer.previewLogsSearch")}</span>
        <strong>INFO</strong>
      </section>
      <div className="chat-theme-preview__logs-layout">
        <aside className="chat-theme-preview__logs-sidebar">
          <ThemeFrame prefix="logs-sidebar" fallbackPrefix="logs-panel" />
          <FileText aria-hidden />
          <strong>session.log</strong>
          <span>128 KB</span>
          <div>
            <small data-level="info">INFO</small>
            <small data-level="warn">WARN</small>
            <small data-level="error">ERROR</small>
          </div>
        </aside>
        <section className="chat-theme-preview__logs-viewer">
          <ThemeFrame prefix="logs-viewer" fallbackPrefix="logs-panel" />
          {["18:42:09", "18:42:11", "18:42:14"].map((time, index) => (
            <div className="chat-theme-preview__log-line" key={time}>
              <span>{index + 42}</span>
              <code>{time}</code>
              <strong>{index === 2 ? "WARN" : "INFO"}</strong>
              <p>{lines[index]}</p>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

function PreviewScene({ mode }: { mode: ChatThemePreviewMode }) {
  const { t } = useI18n();
  if (mode === "logs") {
    return <PreviewLogs />;
  }
  if (mode === "toolbar") {
    return <PreviewToolbar />;
  }
  return (
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
  );
}

export function ChatThemePreview({
  assetThemeId,
  assets,
  assetsLoading,
  manifest,
  mode,
  onModeChange,
  onStateChange,
  onViewportChange,
  state,
  viewport,
}: {
  assetThemeId: string;
  assets: ChatThemeAsset[];
  assetsLoading: boolean;
  manifest: ChatThemeManifest;
  mode: ChatThemePreviewMode;
  onModeChange: (mode: ChatThemePreviewMode) => void;
  onStateChange: (state: ChatThemePreviewState) => void;
  onViewportChange: (viewport: ChatThemePreviewViewport) => void;
  state: ChatThemePreviewState;
  viewport: ChatThemePreviewViewport;
}) {
  const { t } = useI18n();
  const resolved = useMemo(
    () => resolveChatTheme(manifest, (rel) => chatThemeAssetUrl(assetThemeId, rel)),
    [assetThemeId, manifest],
  );
  const diagnostics = useMemo(
    () => diagnoseChatTheme(manifest, assetsLoading ? undefined : assets),
    [assets, assetsLoading, manifest],
  );
  const inputLayout = resolved.style["--chat-input-layout"] === "pill" ? "pill" : "default";

  return (
    <aside className="chat-theme-customizer__preview-panel">
      <div className="chat-theme-customizer__preview-header">
        <div>
          <strong>{t("chat.theme.customizer.preview")}</strong>
          <span>{t("chat.theme.customizer.previewHint")}</span>
        </div>
      </div>
      <div className="chat-theme-customizer__preview-controls">
        <SegmentedTabs
          ariaLabel={t("chat.theme.customizer.preview")}
          items={[
            { id: "dialog", label: t("chat.theme.customizer.previewDialog") },
            { id: "options", label: t("chat.theme.customizer.previewOptions") },
            { id: "toolbar", label: t("chat.theme.customizer.previewToolbar") },
            { id: "logs", label: t("chat.theme.customizer.previewLogs") },
          ]}
          onChange={onModeChange}
          value={mode}
          variant="pills"
        />
        <SegmentedTabs
          ariaLabel={t("chat.theme.customizer.previewState")}
          items={[
            { id: "default", label: t("chat.theme.customizer.stateDefault") },
            { id: "hover", label: t("chat.theme.customizer.stateHover") },
            { id: "active", label: t("chat.theme.customizer.stateActive") },
          ]}
          onChange={onStateChange}
          value={state}
          variant="pills"
        />
        <SegmentedTabs
          ariaLabel={t("chat.theme.customizer.previewViewport")}
          items={[
            { id: "desktop", label: t("chat.theme.customizer.viewportDesktop") },
            { id: "compact", label: t("chat.theme.customizer.viewportCompact") },
            { id: "mobile", label: t("chat.theme.customizer.viewportMobile") },
          ]}
          onChange={onViewportChange}
          value={viewport}
          variant="pills"
        />
      </div>
      <div className="chat-theme-customizer__preview-canvas" data-viewport={viewport}>
        <div
          className="chat-theme-customizer__preview-stage chat-stage"
          data-preview-mode={mode}
          data-preview-state={state}
          data-preview-viewport={viewport}
          style={resolved.style as CSSProperties}
        >
          <div aria-hidden className="chat-theme-customizer__preview-sky">
            <span className="chat-theme-customizer__preview-moon" />
            <span className="chat-theme-customizer__preview-horizon" />
            <span className="chat-theme-customizer__preview-character" />
          </div>
          <PreviewScene mode={mode} />
          {mode === "logs" || mode === "toolbar" ? null : <PreviewInput layout={inputLayout} />}
        </div>
      </div>
      <div className="chat-theme-customizer__diagnostics" data-status={diagnostics.length ? "warning" : "ready"}>
        {diagnostics.length ? <TriangleAlert aria-hidden /> : <CheckCircle2 aria-hidden />}
        <div>
          <strong>
            {t(
              diagnostics.length
                ? "chat.theme.customizer.diagnosticsWarning"
                : "chat.theme.customizer.diagnosticsReady",
            )}
          </strong>
          {diagnostics.map((diagnostic, index) => (
            <span key={`${diagnostic.code}-${diagnostic.section}-${index}`}>
              {t(`chat.theme.customizer.diagnostic.${diagnostic.code}` as const, {
                detail: diagnostic.detail,
                section: diagnostic.section,
              })}
            </span>
          ))}
        </div>
      </div>
    </aside>
  );
}
