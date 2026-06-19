import type { MouseEvent } from "react";
import { Activity, GripHorizontal, Maximize2, Minus, X } from "lucide-react";

import {
  closeDesktopWindow,
  minimizeDesktopWindow,
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
} from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import type { ChatTransportMode, ChatTransportState } from "../../../shared/platform/types";
import { IconButton } from "../../../shared/ui";
import { transportStatusText } from "../chatStageUtils";

export function TopStageTools({
  hidden,
  onTokenUsageOpenChange,
  standaloneDesktopWindow,
  status,
  tokenUsageAvailable,
  tokenUsageOpen,
  transportMode,
  transportState,
}: {
  hidden: boolean;
  onTokenUsageOpenChange: (open: boolean) => void;
  standaloneDesktopWindow: boolean;
  status: string;
  tokenUsageAvailable: boolean;
  tokenUsageOpen: boolean;
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
}) {
  const { t } = useI18n();

  if (hidden) {
    return null;
  }

  const transportText = transportStatusText(t, transportState, transportMode);
  const runWindowAction = (action: () => Promise<void>) => {
    void action().catch((error) => {
      console.error("Desktop chat window action failed", error);
    });
  };

  const handleDragStart = (event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0) {
      return;
    }
    void startDesktopWindowDrag().catch((error) => {
      console.error("Desktop chat window drag failed", error);
    });
  };

  return (
    <div
      className="top-stage-tools"
      data-chat-stage-hitbox="true"
      data-transport-mode={transportMode}
      data-transport-state={transportState}
    >
      <div className="top-stage-tools__status">
        <span className="top-stage-tools__transport">{transportText}</span>
        <span className="top-stage-tools__state">{status}</span>
      </div>
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
          <button
            aria-label={t("desktop.titlebar.drag")}
            className="top-stage-tools__drag"
            data-tauri-drag-region
            onMouseDown={handleDragStart}
            type="button"
          >
            <GripHorizontal aria-hidden className="top-stage-tools__drag-icon" />
          </button>
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
            onClick={() => runWindowAction(closeDesktopWindow)}
          >
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </>
      ) : null}
    </div>
  );
}
