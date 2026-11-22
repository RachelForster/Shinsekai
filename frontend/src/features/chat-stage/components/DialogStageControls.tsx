import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  History,
  Lock,
  Mic,
  MicOff,
  MonitorOff,
  MonitorUp,
  Play,
  RotateCcw,
  ScanLine,
  Settings,
  Shirt,
  SlidersHorizontal,
  Unlock,
  X,
} from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { PluginSlot, type PluginPageTarget } from "../../../shared/plugin/PluginSlot";
import type {
  CharacterOutfitCatalogEntry,
  CharacterOutfitState,
  ChatCommand,
  ChatTurnOptions,
  ChatTurnState,
  MemoryMode,
} from "../../../shared/platform/types";
import { ThemeFrame, ToolbarButton } from "../../../shared/ui";
import { useDismissableLayer } from "../hooks/useDismissableLayer";
import { ChatOutfitPopover } from "./ChatOutfitPopover";
import { ChatTurnSettingsPopover } from "./ChatTurnSettingsPopover";

type DialogControlsDensity = "full" | "tight" | "compact";

function surfaceHorizontalChrome(surface: HTMLElement): number {
  const style = window.getComputedStyle(surface);
  return (
    (Number.parseFloat(style.paddingLeft) || 0) +
    (Number.parseFloat(style.paddingRight) || 0) +
    (Number.parseFloat(style.borderLeftWidth) || 0) +
    (Number.parseFloat(style.borderRightWidth) || 0)
  );
}

function resolveToolbarAvailableWidth(root: HTMLElement): number {
  const container = root.closest<HTMLElement>(".dialog-toolbar-layer, .dialog-layer__toolbar") ?? root.parentElement;
  const paddingX = container
    ? (() => {
        const style = window.getComputedStyle(container);
        return (Number.parseFloat(style.paddingLeft) || 0) + (Number.parseFloat(style.paddingRight) || 0);
      })()
    : 0;
  if (container) {
    const maxWidth = Number.parseFloat(window.getComputedStyle(container).maxWidth);
    if (Number.isFinite(maxWidth) && maxWidth > 0) {
      return Math.max(0, maxWidth - paddingX);
    }
  }
  const stage = root.closest<HTMLElement>(".chat-stage");
  if (stage && stage.clientWidth > 0) {
    const stageStyle = window.getComputedStyle(stage);
    const safeX =
      Number.parseFloat(stageStyle.getPropertyValue("--stage-safe-x")) || (stage.clientWidth <= 860 ? 12 : 24);
    const scale = Number.parseFloat(stageStyle.getPropertyValue("--chat-toolbar-runtime-scale")) || 1;
    return Math.max(0, (stage.clientWidth - 2 * safeX) / Math.max(0.5, scale) - paddingX);
  }
  if (container && container.clientWidth > 0) {
    return Math.max(0, container.clientWidth - paddingX);
  }
  return root.clientWidth;
}

export function DialogStageControls({
  asrEnabled,
  auto,
  autoOutfitSwitch = true,
  bgmVolume,
  effectVolume,
  closeLabel,
  configOpen,
  hideCloseButton,
  hidden,
  longPressTalk,
  locked,
  memoryMode,
  onAutoChange,
  onBgmVolumeChange,
  onEffectVolumeChange,
  onCancelBatch,
  onCloseSurface,
  onCommand,
  onConfigOpenChange,
  onFlushBatch,
  onLongPressTalkChange,
  onLockedChange,
  onOpenHistory,
  onEditConversation,
  onOpenPluginPage,
  onOpenScreenSettings,
  onToggleScreenShare,
  onTurnOptionsChange,
  outfitCatalog,
  outfits,
  screenShareStarting = false,
  screenSharing = false,
  showAsrControl,
  turnOptions,
  turnState,
}: {
  asrEnabled: boolean;
  auto: boolean;
  autoOutfitSwitch?: boolean;
  bgmVolume: number;
  effectVolume: number;
  closeLabel: string;
  configOpen: boolean;
  hidden: boolean;
  hideCloseButton: boolean;
  longPressTalk: boolean;
  locked: boolean;
  memoryMode?: MemoryMode;
  onAutoChange: (auto: boolean) => void;
  onBgmVolumeChange: (value: number) => void;
  onEffectVolumeChange: (value: number) => void;
  onCancelBatch: () => void;
  onCloseSurface: () => void;
  onCommand: (command: ChatCommand) => void;
  onConfigOpenChange: (open: boolean) => void;
  onFlushBatch: () => void;
  onLongPressTalkChange: (value: boolean) => void;
  onLockedChange: (locked: boolean) => void;
  onOpenHistory: () => void;
  onEditConversation?: () => void;
  onOpenPluginPage: (target: PluginPageTarget) => void;
  onOpenScreenSettings?: () => void;
  onToggleScreenShare?: () => void;
  onTurnOptionsChange: (options: ChatTurnOptions) => void;
  outfitCatalog?: Record<string, CharacterOutfitCatalogEntry>;
  outfits?: Record<string, CharacterOutfitState>;
  screenShareStarting?: boolean;
  screenSharing?: boolean;
  showAsrControl: boolean;
  turnOptions: ChatTurnOptions;
  turnState: ChatTurnState;
}) {
  const { t } = useI18n();
  const [chatSettingsOpen, setChatSettingsOpen] = useState(false);
  const [outfitOpen, setOutfitOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const railRef = useRef<HTMLDivElement | null>(null);
  const metricsRef = useRef<{
    density: DialogControlsDensity;
    fullWidth: number;
    signature: string;
    tightWidth: number;
  }>({
    density: "full",
    fullWidth: 0,
    signature: "",
    tightWidth: 0,
  });
  const syncDensity = useCallback((forceRemeasure = false) => {
    const root = rootRef.current;
    const surface = surfaceRef.current;
    const rail = railRef.current;
    if (!root || !surface || !rail) {
      return;
    }
    const signature = `${rail.childElementCount}:${rail.textContent ?? ""}`;
    if (forceRemeasure || metricsRef.current.signature !== signature || metricsRef.current.fullWidth === 0) {
      root.dataset.density = "full";
      const rawFull = rail.scrollWidth;
      const fullWidth = rawFull > 0 ? Math.ceil(rawFull + surfaceHorizontalChrome(surface)) : 0;
      let tightWidth = 0;
      if (fullWidth > 0) {
        root.dataset.density = "tight";
        tightWidth = Math.ceil(rail.scrollWidth + surfaceHorizontalChrome(surface));
      }
      metricsRef.current.signature = signature;
      metricsRef.current.fullWidth = fullWidth;
      metricsRef.current.tightWidth = tightWidth;
    }

    const availableWidth = resolveToolbarAvailableWidth(root);
    const { fullWidth, tightWidth } = metricsRef.current;
    let nextDensity: DialogControlsDensity = "full";
    if (availableWidth > 0 && fullWidth > 0) {
      if (fullWidth <= availableWidth) {
        nextDensity = "full";
      } else if (tightWidth <= availableWidth) {
        nextDensity = "tight";
      } else {
        nextDensity = "compact";
      }
    }
    metricsRef.current.density = nextDensity;
    root.dataset.density = nextDensity;
  }, []);
  const closeChatSettings = useCallback(() => setChatSettingsOpen(false), []);
  const closeOutfitPopover = useCallback(() => setOutfitOpen(false), []);
  const closePopovers = useCallback(() => {
    setChatSettingsOpen(false);
    setOutfitOpen(false);
  }, []);
  useDismissableLayer({ active: chatSettingsOpen || outfitOpen, onDismiss: closePopovers, rootRef });

  const hasSwitchableOutfits = Boolean(
    outfitCatalog && Object.values(outfitCatalog).some((entry) => entry.groups.length > 1),
  );

  useEffect(() => {
    if (hidden) {
      setChatSettingsOpen(false);
      setOutfitOpen(false);
    }
  }, [hidden]);

  useLayoutEffect(() => {
    if (!hidden) {
      syncDensity();
    }
  });

  useLayoutEffect(() => {
    if (hidden) {
      return;
    }
    const root = rootRef.current;
    const rail = railRef.current;
    if (!root || !rail) {
      return;
    }
    let cancelled = false;
    const handleResize = () => {
      if (!cancelled) {
        syncDensity(false);
      }
    };
    const observeTarget =
      root.closest<HTMLElement>(".chat-stage") ??
      root.closest<HTMLElement>(".dialog-toolbar-layer, .dialog-layer__toolbar") ??
      root.parentElement;
    const resizeObserver = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(handleResize);
    if (observeTarget) {
      resizeObserver?.observe(observeTarget);
    }
    const mutationObserver =
      typeof MutationObserver === "undefined"
        ? undefined
        : new MutationObserver(() => {
            if (!cancelled) {
              syncDensity(true);
            }
          });
    mutationObserver?.observe(rail, { characterData: true, childList: true, subtree: true });
    window.addEventListener("resize", handleResize);
    void document.fonts?.ready?.then(() => {
      if (!cancelled) {
        syncDensity(true);
      }
    });
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      window.removeEventListener("resize", handleResize);
    };
  }, [hidden, syncDensity]);

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
      data-density={metricsRef.current.density}
      data-locked={locked ? "true" : "false"}
      onClick={stopDialogActionPropagation}
      onPointerDown={stopDialogPointerPropagation}
      ref={rootRef}
    >
      <div className="dialog-stage-controls__surface" ref={surfaceRef}>
        <ThemeFrame prefix="chat-toolbar" />
        <div
          aria-label={t("chat.actionBar.title")}
          className="dialog-stage-controls__rail"
          ref={railRef}
          role="toolbar"
        >
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
              aria-label={t(asrEnabled ? "chat.toolbar.pauseAsr" : "chat.toolbar.resumeAsr")}
              className="dialog-stage-controls__button"
              data-active={asrEnabled ? "true" : "false"}
              icon={
                asrEnabled ? (
                  <MicOff aria-hidden className="button__icon" />
                ) : (
                  <Mic aria-hidden className="button__icon" />
                )
              }
              onClick={() => onCommand({ type: asrEnabled ? "pause-asr" : "resume-asr" })}
              tooltip={t(asrEnabled ? "chat.toolbar.pauseAsr" : "chat.toolbar.resumeAsr")}
            >
              {t(asrEnabled ? "chat.actionBar.pauseAsr" : "chat.actionBar.resumeAsr")}
            </ToolbarButton>
          ) : null}
          {onToggleScreenShare ? (
            <ToolbarButton
              aria-label={t(screenSharing ? "chat.toolbar.stopShareScreen" : "chat.toolbar.shareScreen")}
              aria-pressed={screenSharing}
              className="dialog-stage-controls__button"
              data-active={screenSharing ? "true" : "false"}
              disabled={screenShareStarting}
              icon={
                screenSharing ? (
                  <MonitorOff aria-hidden className="button__icon" />
                ) : (
                  <MonitorUp aria-hidden className="button__icon" />
                )
              }
              onClick={onToggleScreenShare}
              tooltip={t(screenSharing ? "chat.toolbar.stopShareScreen" : "chat.toolbar.shareScreen")}
            >
              {t(screenSharing ? "chat.actionBar.stopShareScreen" : "chat.actionBar.shareScreen")}
            </ToolbarButton>
          ) : null}
          {screenSharing && onOpenScreenSettings ? (
            <ToolbarButton
              aria-label={t("chat.perception.screenSettings")}
              aria-haspopup="dialog"
              className="dialog-stage-controls__button"
              icon={<ScanLine aria-hidden className="button__icon" />}
              onClick={() => {
                closePopovers();
                onConfigOpenChange(false);
                onOpenScreenSettings();
              }}
              tooltip={t("chat.perception.screenSettings")}
            >
              {t("chat.perception.screenSettings")}
            </ToolbarButton>
          ) : null}
          {hasSwitchableOutfits ? (
            <ToolbarButton
              aria-controls="chat-outfit-popover"
              aria-expanded={outfitOpen}
              aria-label={t("chat.toolbar.outfit")}
              aria-pressed={outfitOpen}
              className="dialog-stage-controls__button"
              data-active={outfitOpen ? "true" : "false"}
              icon={<Shirt aria-hidden className="button__icon" />}
              onClick={() => {
                setChatSettingsOpen(false);
                onConfigOpenChange(false);
                setOutfitOpen((current) => !current);
              }}
              tooltip={t("chat.toolbar.outfit")}
            >
              {t("chat.actionBar.outfit")}
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
              setOutfitOpen(false);
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
              closePopovers();
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
          <PluginSlot onOpenPluginPage={onOpenPluginPage} slot="chat-dialog-actions" />
        </div>
        {hasSwitchableOutfits && outfitCatalog ? (
          <ChatOutfitPopover
            autoOutfitSwitch={autoOutfitSwitch}
            onClose={closeOutfitPopover}
            onCommand={onCommand}
            open={outfitOpen}
            outfitCatalog={outfitCatalog}
            outfits={outfits ?? {}}
          />
        ) : null}
        <ChatTurnSettingsPopover
          onEditConversation={
            onEditConversation
              ? () => {
                  closeChatSettings();
                  onEditConversation();
                }
              : undefined
          }
          bgmVolume={bgmVolume}
          effectVolume={effectVolume}
          longPressTalk={longPressTalk}
          memoryMode={memoryMode}
          onBgmVolumeChange={onBgmVolumeChange}
          onEffectVolumeChange={onEffectVolumeChange}
          onCancelBatch={onCancelBatch}
          onClose={closeChatSettings}
          onFlushBatch={onFlushBatch}
          onLongPressTalkChange={onLongPressTalkChange}
          onMemoryModeChange={
            memoryMode
              ? (nextMode) => onCommand({ type: "set-memory-mode", payload: { memoryMode: nextMode } })
              : undefined
          }
          onTurnOptionsChange={onTurnOptionsChange}
          open={chatSettingsOpen}
          turnOptions={turnOptions}
          turnState={turnState}
        />
      </div>
    </div>
  );
}
