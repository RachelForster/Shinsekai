import type { MouseEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  Copy,
  History,
  Lock,
  Mic,
  MicOff,
  Play,
  RotateCcw,
  SkipForward,
  SlidersHorizontal,
  Trash2,
  Unlock,
  X,
} from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import type { ChatCommand } from "../../../shared/platform/types";
import { ToolbarButton } from "../../../shared/ui";

export function DialogStageControls({
  asrPaused,
  auto,
  closeLabel,
  configOpen,
  hideCloseButton,
  hidden,
  locked,
  onAutoChange,
  onCloseSurface,
  onCommand,
  onConfigOpenChange,
  onLockedChange,
  onOpenHistory,
  showAsrControl,
}: {
  asrPaused: boolean;
  auto: boolean;
  closeLabel: string;
  configOpen: boolean;
  hidden: boolean;
  hideCloseButton: boolean;
  locked: boolean;
  onAutoChange: (auto: boolean) => void;
  onCloseSurface: () => void;
  onCommand: (command: ChatCommand) => void;
  onConfigOpenChange: (open: boolean) => void;
  onLockedChange: (locked: boolean) => void;
  onOpenHistory: () => void;
  showAsrControl: boolean;
}) {
  const { t } = useI18n();
  const stopDialogActionPropagation = (event: MouseEvent<HTMLDivElement>) => {
    event.stopPropagation();
  };
  const stopDialogPointerPropagation = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
  };

  if (hidden) {
    return null;
  }

  const lockLabel = locked ? t("chat.toolbar.unlockActions") : t("chat.toolbar.lockActions");
  const lockText = locked ? t("chat.actionBar.unlock") : t("chat.actionBar.lock");

  return (
    <div
      className="dialog-stage-controls"
      data-chat-stage-hitbox="true"
      data-locked={locked ? "true" : "false"}
      onClick={stopDialogActionPropagation}
      onPointerDown={stopDialogPointerPropagation}
    >
      <div className="dialog-stage-controls__surface">
        <div aria-label={t("chat.actionBar.title")} className="dialog-stage-controls__rail" role="toolbar">
          <ToolbarButton
            aria-label={lockLabel}
            aria-pressed={locked}
            className="dialog-stage-controls__button dialog-stage-controls__button--lock"
            data-active={locked ? "true" : "false"}
            icon={
              locked ? <Lock aria-hidden className="button__icon" /> : <Unlock aria-hidden className="button__icon" />
            }
            onClick={() => onLockedChange(!locked)}
            tooltip={lockLabel}
          >
            {lockText}
          </ToolbarButton>
          <ToolbarButton
            aria-label={t("chat.toolbar.openHistory")}
            className="dialog-stage-controls__button"
            icon={<History aria-hidden className="button__icon" />}
            onClick={onOpenHistory}
            tooltip={t("chat.toolbar.openHistory")}
          >
            {t("chat.actionBar.history")}
          </ToolbarButton>
          <ToolbarButton
            aria-label={t("chat.toolbar.skipSpeech")}
            className="dialog-stage-controls__button"
            icon={<SkipForward aria-hidden className="button__icon" />}
            onClick={() => onCommand({ type: "skip-speech" })}
            tooltip={t("chat.toolbar.skipSpeech")}
          >
            {t("chat.actionBar.skip")}
          </ToolbarButton>
          <ToolbarButton
            aria-label={t("chat.toolbar.autoPlay")}
            aria-pressed={auto}
            className="dialog-stage-controls__button"
            data-active={auto ? "true" : "false"}
            icon={<Play aria-hidden className="button__icon" />}
            onClick={() => onAutoChange(!auto)}
            tooltip={t("chat.toolbar.autoPlay")}
          >
            {t("chat.actionBar.auto")}
          </ToolbarButton>
          <ToolbarButton
            aria-label={t("chat.toolbar.reroll")}
            className="dialog-stage-controls__button"
            icon={<RotateCcw aria-hidden className="button__icon" />}
            onClick={() => onCommand({ type: "reroll" })}
            tooltip={t("chat.toolbar.reroll")}
          >
            {t("chat.actionBar.reroll")}
          </ToolbarButton>
          {showAsrControl ? (
            <ToolbarButton
              aria-label={asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}
              className="dialog-stage-controls__button"
              data-active={asrPaused ? "true" : "false"}
              icon={
                asrPaused ? (
                  <Mic aria-hidden className="button__icon" />
                ) : (
                  <MicOff aria-hidden className="button__icon" />
                )
              }
              onClick={() => onCommand({ type: asrPaused ? "resume-asr" : "pause-asr" })}
              tooltip={asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}
            >
              {t(asrPaused ? "chat.actionBar.resumeAsr" : "chat.actionBar.pauseAsr")}
            </ToolbarButton>
          ) : null}
          <ToolbarButton
            aria-label={t("chat.toolbar.copyHistory")}
            className="dialog-stage-controls__button"
            icon={<Copy aria-hidden className="button__icon" />}
            onClick={() => onCommand({ type: "copy-history" })}
            tooltip={t("chat.toolbar.copyHistory")}
          >
            {t("chat.actionBar.copy")}
          </ToolbarButton>
          <ToolbarButton
            aria-label={t("chat.toolbar.clearHistory")}
            className="dialog-stage-controls__button dialog-stage-controls__button--danger"
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={() => onCommand({ type: "clear-history" })}
            tooltip={t("chat.toolbar.clearHistory")}
          >
            {t("chat.actionBar.clear")}
          </ToolbarButton>
          <ToolbarButton
            aria-controls="chat-stage-dialog-config"
            aria-expanded={configOpen}
            aria-label={t("chat.toolbar.config")}
            aria-pressed={configOpen}
            className="dialog-stage-controls__button"
            data-active={configOpen ? "true" : "false"}
            icon={<SlidersHorizontal aria-hidden className="button__icon" />}
            onClick={() => onConfigOpenChange(!configOpen)}
            tooltip={t("chat.toolbar.config")}
          >
            {t("chat.actionBar.config")}
          </ToolbarButton>
          {hideCloseButton ? null : (
            <ToolbarButton
              aria-label={closeLabel}
              className="dialog-stage-controls__button"
              icon={<X aria-hidden className="button__icon" />}
              onClick={onCloseSurface}
              tooltip={closeLabel}
            >
              {t("chat.actionBar.close")}
            </ToolbarButton>
          )}
          <PluginSlot slot="chat-dialog-actions" />
        </div>
      </div>
    </div>
  );
}
