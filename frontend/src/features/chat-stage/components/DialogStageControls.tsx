import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  GitBranch,
  History,
  Lock,
  Mic,
  MicOff,
  Play,
  RotateCcw,
  Settings,
  SlidersHorizontal,
  Unlock,
  X,
} from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import type { ChatCommand, ChatTurnOptions, ChatTurnState } from "../../../shared/platform/types";
import { ThemeFrame, ToolbarButton } from "../../../shared/ui";
import { useDismissableLayer } from "../hooks/useDismissableLayer";
import { ChatTurnSettingsPopover } from "./ChatTurnSettingsPopover";

export function DialogStageControls({
  asrPaused,
  auto,
  closeLabel,
  configOpen,
  hideCloseButton,
  hidden,
  locked,
  onAutoChange,
  onCancelBatch,
  onCloseSurface,
  onCommand,
  onConfigOpenChange,
  onFlushBatch,
  onLockedChange,
  onOpenBranches,
  onOpenHistory,
  onTurnOptionsChange,
  showBranches,
  showAsrControl,
  turnOptions,
  turnState,
}: {
  asrPaused: boolean;
  auto: boolean;
  closeLabel: string;
  configOpen: boolean;
  hidden: boolean;
  hideCloseButton: boolean;
  locked: boolean;
  onAutoChange: (auto: boolean) => void;
  onCancelBatch: () => void;
  onCloseSurface: () => void;
  onCommand: (command: ChatCommand) => void;
  onConfigOpenChange: (open: boolean) => void;
  onFlushBatch: () => void;
  onLockedChange: (locked: boolean) => void;
  onOpenBranches: () => void;
  onOpenHistory: () => void;
  onTurnOptionsChange: (options: ChatTurnOptions) => void;
  showBranches: boolean;
  showAsrControl: boolean;
  turnOptions: ChatTurnOptions;
  turnState: ChatTurnState;
}) {
  const { t } = useI18n();
  const [chatSettingsOpen, setChatSettingsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const closeChatSettings = useCallback(() => setChatSettingsOpen(false), []);
  useDismissableLayer({ active: chatSettingsOpen, onDismiss: closeChatSettings, rootRef });

  useEffect(() => {
    if (hidden) {
      setChatSettingsOpen(false);
    }
  }, [hidden]);

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
  const branchTooltip = showBranches
    ? t("chat.toolbar.openBranches")
    : t("chat.toolbar.openBranchesExperimentalDisabled");

  return (
    <div
      className="dialog-stage-controls"
      data-chat-stage-hitbox="true"
      data-locked={locked ? "true" : "false"}
      onClick={stopDialogActionPropagation}
      onPointerDown={stopDialogPointerPropagation}
      ref={rootRef}
    >
      <div className="dialog-stage-controls__surface">
        <ThemeFrame prefix="chat-toolbar" />
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
            aria-disabled={!showBranches}
            aria-label={branchTooltip}
            className="dialog-stage-controls__button"
            data-experimental="true"
            disabled={!showBranches}
            icon={<GitBranch aria-hidden className="button__icon" />}
            onClick={onOpenBranches}
            tooltip={branchTooltip}
          >
            {t("chat.actionBar.branches")}
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
            aria-controls="chat-turn-settings-popover"
            aria-expanded={chatSettingsOpen}
            aria-label={t("chat.input.settings")}
            aria-pressed={chatSettingsOpen}
            className="dialog-stage-controls__button"
            data-active={chatSettingsOpen ? "true" : "false"}
            icon={<Settings aria-hidden className="button__icon" />}
            onClick={() => {
              onConfigOpenChange(false);
              setChatSettingsOpen((current) => !current);
            }}
            tooltip={t("chat.input.settings")}
          >
            {t("chat.input.settings")}
          </ToolbarButton>
          <ToolbarButton
            aria-controls="chat-stage-dialog-config"
            aria-expanded={configOpen}
            aria-label={t("chat.toolbar.config")}
            aria-pressed={configOpen}
            className="dialog-stage-controls__button"
            data-active={configOpen ? "true" : "false"}
            icon={<SlidersHorizontal aria-hidden className="button__icon" />}
            onClick={() => {
              closeChatSettings();
              onConfigOpenChange(!configOpen);
            }}
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
        <ChatTurnSettingsPopover
          onCancelBatch={onCancelBatch}
          onClose={closeChatSettings}
          onFlushBatch={onFlushBatch}
          onTurnOptionsChange={onTurnOptionsChange}
          open={chatSettingsOpen}
          turnOptions={turnOptions}
          turnState={turnState}
        />
      </div>
    </div>
  );
}
