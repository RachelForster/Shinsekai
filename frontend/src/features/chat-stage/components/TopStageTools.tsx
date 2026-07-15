import { Activity, Maximize2, Minus, X } from "lucide-react";

import { minimizeDesktopWindow, toggleMaximizeDesktopWindow } from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import type { ChatTransportMode, ChatTransportState } from "../../../shared/platform/types";
import { IconButton, ThemeFrame } from "../../../shared/ui";
import { transportStatusText } from "../chatStageUtils";
import { useAutoHideRegion } from "../hooks/useAutoHideRegion";

export function TopStageTools({
  autoHide = false,
  hidden,
  onCloseDesktopWindow,
  onTokenUsageOpenChange,
  standaloneDesktopWindow,
  status,
  tokenUsageAvailable,
  tokenUsageOpen,
  transportMode,
  transportState,
}: {
  autoHide?: boolean;
  hidden: boolean;
  onCloseDesktopWindow: () => Promise<void>;
  onTokenUsageOpenChange: (open: boolean) => void;
  standaloneDesktopWindow: boolean;
  status: string;
  tokenUsageAvailable: boolean;
  tokenUsageOpen: boolean;
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
}) {
  const { t } = useI18n();
  const autoHideRegion = useAutoHideRegion({ enabled: autoHide, forceVisible: tokenUsageOpen });

  if (hidden) {
    return null;
  }

  const transportText = transportStatusText(t, transportState, transportMode);
  const runWindowAction = (action: () => Promise<void>) => {
    void action().catch((error) => {
      console.error("Desktop chat window action failed", error);
    });
  };

  return (
    <div
      aria-label={t("chat.toolbar.tools")}
      className="top-stage-tools"
      data-auto-hide={autoHide ? "true" : "false"}
      data-chat-stage-hitbox="true"
      data-standalone-desktop={standaloneDesktopWindow ? "true" : "false"}
      data-force-visible={tokenUsageOpen ? "true" : "false"}
      data-transport-mode={transportMode}
      data-transport-state={transportState}
      data-visible={autoHideRegion.visible ? "true" : "false"}
      onBlurCapture={autoHideRegion.handleBlur}
      onFocusCapture={autoHideRegion.handleFocus}
      onPointerEnter={autoHideRegion.show}
      onPointerLeave={autoHideRegion.scheduleHide}
      role="toolbar"
      style={autoHideRegion.visible ? undefined : { pointerEvents: "none" }}
      tabIndex={0}
    >
      <ThemeFrame prefix="chat-toolbar" />
      <div className="top-stage-tools__status">
        <span className="top-stage-tools__transport">{transportText}</span>
        <span className="top-stage-tools__state">{status}</span>
      </div>
      <div className="top-stage-tools__controls">
        <IconButton
          aria-pressed={tokenUsageOpen}
          className="top-stage-tools__button"
          data-active={tokenUsageOpen ? "true" : "false"}
          disabled={!tokenUsageAvailable}
          label={t("chat.toolbar.tokens")}
          onClick={() => onTokenUsageOpenChange(!tokenUsageOpen)}
        >
          <Activity aria-hidden className="icon-button__icon" />
        </IconButton>
        {standaloneDesktopWindow ? (
          <>
            <IconButton
              className="top-stage-tools__button"
              label={t("desktop.titlebar.minimize")}
              onClick={() => runWindowAction(minimizeDesktopWindow)}
            >
              <Minus aria-hidden className="icon-button__icon" />
            </IconButton>
            <IconButton
              className="top-stage-tools__button"
              label={t("desktop.titlebar.maximize")}
              onClick={() => runWindowAction(toggleMaximizeDesktopWindow)}
            >
              <Maximize2 aria-hidden className="icon-button__icon" />
            </IconButton>
            <IconButton
              className="top-stage-tools__button"
              label={t("desktop.titlebar.close")}
              onClick={() => runWindowAction(onCloseDesktopWindow)}
            >
              <X aria-hidden className="icon-button__icon" />
            </IconButton>
          </>
        ) : null}
      </div>
    </div>
  );
}
