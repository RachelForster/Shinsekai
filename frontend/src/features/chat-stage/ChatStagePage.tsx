import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type ChangeEvent,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
  type SyntheticEvent,
} from "react";
import {
  Activity,
  Copy,
  GripHorizontal,
  History,
  Languages,
  Maximize2,
  Mic,
  MicOff,
  Minus,
  MoreHorizontal,
  RotateCcw,
  Send,
  SlidersHorizontal,
  SkipForward,
  Trash2,
  X,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  closeChat,
  getChatHistory,
  getChatSnapshot,
  sendChatCommand,
  subscribeChatEvents,
} from "../../entities/chat/repository";
import {
  closeDesktopWindow,
  getDesktopWindowCursorPosition,
  isTauriDesktop,
  minimizeDesktopWindow,
  setDesktopWindowClickThrough,
  startDesktopWindowDrag,
  startDesktopWindowResize,
  toggleMaximizeDesktopWindow,
  type DesktopResizeDirection,
} from "../../shared/desktop/desktopApi";
import { closeChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import type { MessageKey } from "../../shared/i18n";
import { PluginSlot } from "../../shared/plugin/PluginSlot";
import type {
  ChatCommand,
  ChatHistoryEntry,
  ChatSnapshot,
  ChatTransportMode,
  ChatTransportState,
} from "../../shared/platform/types";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";
import { AlertDialog, Button, IconButton, Select, TextArea, ToolbarButton, useToast } from "../../shared/ui";
import "./chat-stage.css";
import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "./chatState";
import type { ChatStageSprite } from "./chatState";
import { buildDialogTypewriterSource, renderDialogTypewriterFrame } from "./dialogTypewriter";
import { useOptionalChatTheme } from "./theme/ChatThemeProvider";

const chatVoiceLanguages = [
  { labelKey: "system.asr.langJa", value: "ja" },
  { labelKey: "system.asr.langEn", value: "en" },
  { labelKey: "system.asr.langZh", value: "zh" },
  { labelKey: "system.asr.langYue", value: "yue" },
] as const;

interface BrowserSpeechRecognition {
  abort: () => void;
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: { error?: string; message?: string }) => void) | null;
  onresult:
    | ((event: { resultIndex: number; results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void)
    | null;
  start: () => void;
  stop: () => void;
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

function getSpeechRecognitionConstructor(): BrowserSpeechRecognitionConstructor | null {
  const scope = window as typeof window & {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}

function speechRecognitionLanguage(language: string) {
  if (language === "en") {
    return "en-US";
  }
  if (language === "ja") {
    return "ja-JP";
  }
  return "zh-CN";
}

function cleanTranscript(text: string, language: string) {
  const trimmed = text.trim();
  if (language === "en") {
    return trimmed;
  }
  return trimmed.replace(/\s+/g, "");
}

function appendTranscript(base: string, transcript: string, language: string) {
  const text = cleanTranscript(transcript, language);
  if (!text) {
    return base;
  }
  const current = base.trim();
  if (!current) {
    return text;
  }
  const separator = language === "en" ? " " : "，";
  if (/[，。！？,.!?;；:：\s]$/.test(current)) {
    return `${current}${text}`;
  }
  return `${current}${separator}${text}`;
}

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function eventTargetElement(target: EventTarget | null) {
  if (target instanceof Element) {
    return target;
  }
  if (target instanceof Node) {
    return target.parentElement;
  }
  return null;
}

function isChatStageHitbox(target: EventTarget | null) {
  return Boolean(eventTargetElement(target)?.closest("[data-chat-stage-hitbox='true']"));
}

function isPointInsideChatStageHitbox(x: number, y: number) {
  const hitboxes = document.querySelectorAll<HTMLElement>("[data-chat-stage-hitbox='true']");
  for (const hitbox of hitboxes) {
    if (hitbox.hidden || hitbox.getAttribute("aria-hidden") === "true") {
      continue;
    }
    const rect = hitbox.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      continue;
    }
    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
      return true;
    }
  }
  return false;
}

function layerClassName(base: string, hidden: boolean) {
  return classNames(base, hidden && "chat-stage__layer--hidden");
}

const clickThroughGuardIntervalMs = 32;
const runtimeConfigStorageKey = "shinsekai-chat-stage-runtime-config";
const runtimeTextSpeedMin = 1;
const runtimeTextSpeedMax = 200;
const runtimeDialogOpacityMin = 0.35;
const runtimeDialogOpacityMax = 1;
const runtimeDialogOpacityStep = 0.05;

interface ChatStageRuntimeConfig {
  dialogOpacity: number;
  typewriterCps: number | null;
}

const defaultChatStageRuntimeConfig: ChatStageRuntimeConfig = {
  dialogOpacity: 1,
  typewriterCps: null,
};

function clampRuntimeNumber(value: unknown, fallback: number, min: number, max: number) {
  const next = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(next)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, next));
}

function readChatStageRuntimeConfig(): ChatStageRuntimeConfig {
  if (typeof window === "undefined") {
    return defaultChatStageRuntimeConfig;
  }
  try {
    const raw = window.localStorage.getItem(runtimeConfigStorageKey);
    if (!raw) {
      return defaultChatStageRuntimeConfig;
    }
    const parsed = JSON.parse(raw) as Partial<ChatStageRuntimeConfig>;
    return {
      dialogOpacity: clampRuntimeNumber(
        parsed.dialogOpacity,
        defaultChatStageRuntimeConfig.dialogOpacity,
        runtimeDialogOpacityMin,
        runtimeDialogOpacityMax,
      ),
      typewriterCps:
        parsed.typewriterCps == null
          ? null
          : Math.round(
              clampRuntimeNumber(
                parsed.typewriterCps,
                DEFAULT_TYPEWRITER_CPS,
                runtimeTextSpeedMin,
                runtimeTextSpeedMax,
              ),
            ),
    };
  } catch {
    return defaultChatStageRuntimeConfig;
  }
}

function writeChatStageRuntimeConfig(config: ChatStageRuntimeConfig) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(runtimeConfigStorageKey, JSON.stringify(config));
  } catch {
    // localStorage may be unavailable in hardened webviews.
  }
}

const desktopResizeHandles: Array<{ className: string; direction: DesktopResizeDirection }> = [
  { className: "desktop-resize-handle--n", direction: "North" },
  { className: "desktop-resize-handle--e", direction: "East" },
  { className: "desktop-resize-handle--s", direction: "South" },
  { className: "desktop-resize-handle--w", direction: "West" },
  { className: "desktop-resize-handle--ne", direction: "NorthEast" },
  { className: "desktop-resize-handle--nw", direction: "NorthWest" },
  { className: "desktop-resize-handle--se", direction: "SouthEast" },
  { className: "desktop-resize-handle--sw", direction: "SouthWest" },
];

function hideBrokenStageAsset(event: SyntheticEvent<HTMLImageElement>) {
  event.currentTarget.dataset.loadState = "error";
}

function transportStatusText(t: (key: MessageKey) => string, state: ChatTransportState, mode: ChatTransportMode) {
  if (state === "connected") {
    return mode === "websocket" ? t("chat.transport.connected") : t("chat.transport.snapshot");
  }
  if (state === "polling") {
    return t("chat.transport.polling");
  }
  if (state === "reconnecting") {
    return t("chat.transport.reconnecting");
  }
  return t("chat.transport.connecting");
}

function BackgroundLayer({ hidden, path, transparent }: { hidden: boolean; path?: string; transparent: boolean }) {
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__background", hidden)}
      data-transparent={transparent ? "true" : "false"}
      hidden={hidden}
    >
      {transparent ? null : <div aria-hidden className="chat-stage__fallback" />}
      {path ? <img alt="" onError={hideBrokenStageAsset} src={path} /> : null}
    </div>
  );
}

function CgLayer({ hidden, path }: { hidden: boolean; path?: string }) {
  return (
    <div aria-hidden={hidden} className={layerClassName("chat-stage__cg", hidden)} hidden={hidden}>
      {path ? <img alt="" onError={hideBrokenStageAsset} src={path} /> : null}
    </div>
  );
}

function SpriteLayer({ hidden, sprites }: { hidden: boolean; sprites: ChatStageSprite[] }) {
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("sprite-layer", hidden)}
      data-count={sprites.length}
      hidden={hidden}
    >
      {sprites.map((sprite, index) => (
        <figure
          className="sprite-layer__figure"
          data-slot={sprite.slot ?? index}
          key={sprite.id}
          style={
            {
              "--sprite-count": sprites.length,
              "--sprite-index": index,
              "--sprite-scale": sprite.scale ?? 1,
            } as CSSProperties
          }
        >
          <img alt={sprite.label} className="sprite-layer__image" onError={hideBrokenStageAsset} src={sprite.path} />
        </figure>
      ))}
    </div>
  );
}

function DialogLayer({
  canAdvance,
  characterName,
  hidden,
  html,
  onAdvance,
  onSkip,
  text,
  typing,
}: {
  canAdvance: boolean;
  characterName?: string;
  hidden: boolean;
  html?: string;
  onAdvance?: () => void;
  onSkip?: () => void;
  text: string;
  typing: boolean;
}) {
  return (
    <section
      aria-hidden={hidden}
      aria-live="polite"
      className={layerClassName("dialog-layer", hidden)}
      data-chat-stage-hitbox="true"
      data-typing={typing ? "true" : "false"}
      hidden={hidden}
      onClick={typing ? onSkip : canAdvance ? onAdvance : undefined}
    >
      {characterName ? <p className="dialog-layer__name">{characterName}</p> : null}
      {html !== undefined ? (
        <p className="dialog-layer__text" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <p className="dialog-layer__text">{text}</p>
      )}
      <PluginSlot slot="chat-output" />
    </section>
  );
}

function OptionsLayer({
  hidden,
  onSelect,
  options,
}: {
  hidden: boolean;
  onSelect: (option: string) => void;
  options: string[];
}) {
  if (hidden || !options.length) {
    return null;
  }
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("options-layer", hidden)}
      data-chat-stage-hitbox="true"
      hidden={hidden}
    >
      {options.map((option) => (
        <Button className="options-layer__button" key={option} onClick={() => onSelect(option)}>
          {option}
        </Button>
      ))}
    </div>
  );
}

function BusyLayer({ hidden, text }: { hidden: boolean; text?: string }) {
  if (hidden || !text) {
    return null;
  }
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__busy", hidden)}
      data-chat-stage-hitbox="true"
      hidden={hidden}
      role="status"
    >
      {text}
    </div>
  );
}

function NotificationLayer({ hidden, text }: { hidden: boolean; text?: string }) {
  if (hidden || !text) {
    return null;
  }
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__notification", hidden)}
      data-chat-stage-hitbox="true"
      hidden={hidden}
    >
      {text}
    </div>
  );
}

function tokenUsageSegments(text: string) {
  return text
    .split(/\n|\|/g)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

function TokenUsageLayer({ hidden, text }: { hidden: boolean; text?: string }) {
  if (hidden || !text) {
    return null;
  }
  const segments = tokenUsageSegments(text);
  return (
    <section className="token-usage-layer" data-chat-stage-hitbox="true" role="status">
      <span className="token-usage-layer__title">TOKENS</span>
      <div className="token-usage-layer__content">
        {segments.length > 1 ? (
          segments.map((segment, index) => (
            <span className="token-usage-layer__chip" key={`${segment}-${index}`}>
              {segment}
            </span>
          ))
        ) : (
          <span className="token-usage-layer__raw">{text}</span>
        )}
      </div>
    </section>
  );
}

function StandaloneDesktopWindowControls({ hidden }: { hidden: boolean }) {
  const { t } = useI18n();

  if (hidden) {
    return null;
  }

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
    <div className="desktop-chat-controls" data-chat-stage-hitbox="true">
      <div className="desktop-chat-controls__drag" data-tauri-drag-region onMouseDown={handleDragStart}>
        <GripHorizontal aria-hidden className="desktop-chat-controls__drag-icon" />
      </div>
      <div className="desktop-chat-controls__buttons">
        <IconButton label={t("desktop.titlebar.minimize")} onClick={() => runWindowAction(minimizeDesktopWindow)}>
          <Minus aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton label={t("desktop.titlebar.maximize")} onClick={() => runWindowAction(toggleMaximizeDesktopWindow)}>
          <Maximize2 aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton label={t("desktop.titlebar.close")} onClick={() => runWindowAction(closeDesktopWindow)}>
          <X aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
    </div>
  );
}

function StandaloneDesktopResizeHandles({ hidden }: { hidden: boolean }) {
  if (hidden) {
    return null;
  }

  const handleResizeStart = (direction: DesktopResizeDirection) => (event: MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    void startDesktopWindowResize(direction).catch((error) => {
      console.error("Desktop chat window resize failed", error);
    });
  };

  return (
    <div aria-hidden className="desktop-resize-handles">
      {desktopResizeHandles.map((handle) => (
        <div
          className={classNames("desktop-resize-handle", handle.className)}
          data-chat-stage-hitbox="true"
          key={handle.direction}
          onMouseDown={handleResizeStart(handle.direction)}
        />
      ))}
    </div>
  );
}

const defaultUserDisplayName = "你";

function normalizeUserDisplayName(value?: string) {
  return value?.trim() || defaultUserDisplayName;
}

function userSpeakerPrefixPattern(userDisplayName: string) {
  const names = [defaultUserDisplayName, userDisplayName]
    .map((name) => name.trim())
    .filter(Boolean)
    .filter((name, index, list) => list.indexOf(name) === index)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`^\\s*(${names.join("|")})\\s*[：:]\\s*([\\s\\S]*)$`);
}

function historySpeakerFallback(role: ChatHistoryEntry["role"], userDisplayName: string) {
  if (role === "user") {
    return userDisplayName;
  }
  if (role === "assistant") {
    return "角色";
  }
  if (role === "options") {
    return "选项";
  }
  return "旁白";
}

function historyRoleLabel(role: ChatHistoryEntry["role"]) {
  if (role === "user") {
    return "USER";
  }
  if (role === "assistant") {
    return "CHARACTER";
  }
  if (role === "options") {
    return "CHOICE";
  }
  return "SYSTEM";
}

function historyEntryLocalTime(entry: ChatHistoryEntry) {
  const raw = entry.createdAt;
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    return "";
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function splitHistoryEntryText(entry: ChatHistoryEntry, userDisplayName: string) {
  const userName = normalizeUserDisplayName(userDisplayName);
  if (entry.role === "user") {
    const userMatch = entry.text.match(userSpeakerPrefixPattern(userName));
    return {
      body: (userMatch?.[2] ?? entry.text).trimStart(),
      localTime: historyEntryLocalTime(entry),
      speaker: userMatch?.[1] === defaultUserDisplayName ? userName : userMatch?.[1]?.trim() || userName,
    };
  }
  const match = entry.text.match(/^\s*([^：:\n]{1,36})\s*[：:]\s*([\s\S]*)$/);
  if (!match) {
    return { body: entry.text, localTime: "", speaker: historySpeakerFallback(entry.role, userName) };
  }
  return {
    body: match[2]?.trimStart() ?? "",
    localTime: "",
    speaker: match[1]?.trim() || historySpeakerFallback(entry.role, userName),
  };
}

function HistoryDialog({
  entries,
  loading,
  onClose,
  onRefresh,
  onRevert,
  open,
  userDisplayName,
}: {
  entries: ChatHistoryEntry[];
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onRevert: (userIndex: number) => void;
  open: boolean;
  userDisplayName: string;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    return () => previous?.focus();
  }, [open]);

  if (!open) {
    return null;
  }

  const onBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  };

  return (
    <div className="chat-history-backdrop" onMouseDown={onBackdropMouseDown} role="presentation">
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="chat-history-dialog"
        onKeyDown={onKeyDown}
        role="dialog"
      >
        <header className="chat-history-dialog__header">
          <div className="chat-history-dialog__heading">
            <p className="chat-history-dialog__eyebrow">LOG</p>
            <h2 className="chat-history-dialog__title" id={titleId}>
              {t("chat.history.title")}
            </h2>
          </div>
          <IconButton
            className="chat-history-dialog__close"
            label={t("common.close")}
            onClick={onClose}
            ref={closeButtonRef}
          >
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </header>
        <div className="chat-history-dialog__body">
          {loading ? <p className="chat-history__empty">{t("chat.history.loading")}</p> : null}
          {!loading && entries.length === 0 ? <p className="chat-history__empty">{t("chat.history.empty")}</p> : null}
          {!loading && entries.length > 0 ? (
            <div className="chat-history__list">
              {entries.map((entry) => {
                const dialog = splitHistoryEntryText(entry, userDisplayName);
                return (
                  <section className="chat-history__entry" data-role={entry.role} key={entry.id}>
                    <div className="chat-history__speaker-row">
                      <span className="chat-history__speaker">{dialog.speaker}</span>
                      {entry.role === "user" && dialog.localTime ? (
                        <span className="chat-history__time">{dialog.localTime}</span>
                      ) : null}
                      <span className="chat-history__role">{historyRoleLabel(entry.role)}</span>
                    </div>
                    <p className="chat-history__text">{dialog.body}</p>
                    {entry.role === "user" && entry.revertUserIndex != null ? (
                      <div className="chat-history__actions">
                        <Button
                          className="chat-history__revert"
                          icon={<RotateCcw aria-hidden className="button__icon" />}
                          onClick={() => onRevert(entry.revertUserIndex!)}
                        >
                          {t("chat.history.revert")}
                        </Button>
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          ) : null}
        </div>
        <footer className="chat-history-dialog__footer">
          <Button onClick={onRefresh}>{t("common.refresh")}</Button>
          <Button onClick={onClose}>{t("common.close")}</Button>
        </footer>
      </section>
    </div>
  );
}

function FloatingToolbar({
  asrPaused,
  closeLabel,
  configOpen,
  dialogOpacity,
  hidden,
  hideCloseButton,
  open,
  onCloseSurface,
  onCommand,
  onConfigOpenChange,
  onDialogOpacityChange,
  onOpenChange,
  onOpenHistory,
  onTextSpeedChange,
  onTokenUsageOpenChange,
  status,
  textSpeed,
  tokenUsageAvailable,
  tokenUsageOpen,
  transportMode,
  transportState,
  voiceLanguage,
}: {
  asrPaused: boolean;
  closeLabel: string;
  configOpen: boolean;
  dialogOpacity: number;
  hidden: boolean;
  hideCloseButton: boolean;
  open: boolean;
  onCloseSurface: () => void;
  onCommand: (command: ChatCommand) => void;
  onConfigOpenChange: (open: boolean) => void;
  onDialogOpacityChange: (value: number) => void;
  onOpenChange: (open: boolean) => void;
  onOpenHistory: () => void;
  onTextSpeedChange: (value: number) => void;
  onTokenUsageOpenChange: (open: boolean) => void;
  status: string;
  textSpeed: number;
  tokenUsageAvailable: boolean;
  tokenUsageOpen: boolean;
  transportMode: ChatTransportMode;
  transportState: ChatTransportState;
  voiceLanguage: string;
}) {
  const { t } = useI18n();
  const toolbarRef = useRef<HTMLDivElement | null>(null);
  const dialogOpacityPercent = Math.round(dialogOpacity * 100);
  const setToolsOpen = useCallback(
    (nextOpen: boolean) => {
      onOpenChange(nextOpen);
      if (!nextOpen) {
        onConfigOpenChange(false);
      }
    },
    [onConfigOpenChange, onOpenChange],
  );

  useEffect(() => {
    if (hidden || !open) {
      return;
    }

    const closeIfOutside = (event: globalThis.PointerEvent) => {
      const target = eventTargetElement(event.target);
      if (!target) {
        return;
      }
      if (toolbarRef.current?.contains(target)) {
        return;
      }
      if (target.closest(".custom-select__menu, .dialog-backdrop")) {
        return;
      }
      setToolsOpen(false);
    };

    document.addEventListener("pointerdown", closeIfOutside, true);
    return () => {
      document.removeEventListener("pointerdown", closeIfOutside, true);
    };
  }, [hidden, open, setToolsOpen]);

  if (hidden) {
    return null;
  }

  const transportText = transportStatusText(t, transportState, transportMode);
  const closeToolsWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      setToolsOpen(false);
    }
  };
  const handleTextSpeedChange = (event: ChangeEvent<HTMLInputElement>) => {
    onTextSpeedChange(
      Math.round(clampRuntimeNumber(event.target.value, textSpeed, runtimeTextSpeedMin, runtimeTextSpeedMax)),
    );
  };
  const handleDialogOpacityChange = (event: ChangeEvent<HTMLInputElement>) => {
    onDialogOpacityChange(
      clampRuntimeNumber(event.target.value, dialogOpacity, runtimeDialogOpacityMin, runtimeDialogOpacityMax),
    );
  };
  return (
    <div
      className="floating-toolbar"
      data-chat-stage-hitbox="true"
      data-open={open ? "true" : "false"}
      data-transport-mode={transportMode}
      data-transport-state={transportState}
      onKeyDown={closeToolsWithKeyboard}
      ref={toolbarRef}
    >
      <div className="floating-toolbar__summary">
        <span className="floating-toolbar__meta">
          <span className="floating-toolbar__transport">{transportText}</span>
          <span className="floating-toolbar__status">{status}</span>
        </span>
        <IconButton
          aria-controls="chat-stage-toolbar-panel"
          aria-expanded={open}
          className="floating-toolbar__menu-trigger"
          label={t("chat.toolbar.tools")}
          onClick={() => setToolsOpen(!open)}
        >
          <MoreHorizontal aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      <div aria-hidden={!open} className="floating-toolbar__panel" hidden={!open} id="chat-stage-toolbar-panel">
        <div className="floating-toolbar__panel-head">
          <span className="floating-toolbar__panel-title">{t("chat.toolbar.tools")}</span>
          <div className="floating-toolbar__panel-toggles">
            <IconButton
              aria-pressed={tokenUsageOpen}
              className="floating-toolbar__token-trigger"
              data-active={tokenUsageOpen ? "true" : "false"}
              disabled={!tokenUsageAvailable}
              label={t("chat.toolbar.tokens")}
              onClick={() => onTokenUsageOpenChange(!tokenUsageOpen)}
            >
              <Activity aria-hidden className="icon-button__icon" />
            </IconButton>
            <IconButton
              aria-controls="chat-stage-toolbar-config"
              aria-expanded={configOpen}
              aria-pressed={configOpen}
              className="floating-toolbar__config-trigger"
              data-active={configOpen ? "true" : "false"}
              label={t("chat.toolbar.config")}
              onClick={() => onConfigOpenChange(!configOpen)}
            >
              <SlidersHorizontal aria-hidden className="icon-button__icon" />
            </IconButton>
          </div>
        </div>
        <div aria-label={t("chat.toolbar.tools")} className="floating-toolbar__actions" role="group">
          <IconButton label={t("chat.toolbar.openHistory")} onClick={onOpenHistory}>
            <History aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton label={t("chat.toolbar.reroll")} onClick={() => onCommand({ type: "reroll" })}>
            <RotateCcw aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton
            label={asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}
            onClick={() => onCommand({ type: asrPaused ? "resume-asr" : "pause-asr" })}
          >
            {asrPaused ? (
              <Mic aria-hidden className="icon-button__icon" />
            ) : (
              <MicOff aria-hidden className="icon-button__icon" />
            )}
          </IconButton>
          <IconButton label={t("chat.toolbar.copyHistory")} onClick={() => onCommand({ type: "copy-history" })}>
            <Copy aria-hidden className="icon-button__icon" />
          </IconButton>
          <IconButton label={t("chat.toolbar.clearHistory")} onClick={() => onCommand({ type: "clear-history" })}>
            <Trash2 aria-hidden className="icon-button__icon" />
          </IconButton>
          {hideCloseButton ? null : (
            <IconButton label={closeLabel} onClick={onCloseSurface}>
              <X aria-hidden className="icon-button__icon" />
            </IconButton>
          )}
          <ToolbarButton
            className="floating-toolbar__skip"
            icon={<SkipForward aria-hidden className="button__icon" />}
            onClick={() => onCommand({ type: "skip-speech" })}
          >
            {t("chat.toolbar.skipSpeech")}
          </ToolbarButton>
        </div>
        <div
          aria-hidden={!configOpen}
          className="floating-toolbar__config-panel"
          hidden={!configOpen}
          id="chat-stage-toolbar-config"
        >
          <label className="floating-toolbar__config-row floating-toolbar__voice">
            <span className="floating-toolbar__config-label">
              <Languages aria-hidden className="floating-toolbar__voice-icon" />
              {t("template.field.voiceLanguage")}
            </span>
            <Select
              aria-label={t("template.field.voiceLanguage")}
              className="floating-toolbar__voice-select"
              onChange={(event) => onCommand({ payload: event.target.value, type: "change-voice-language" })}
              value={voiceLanguage}
            >
              {chatVoiceLanguages.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </Select>
          </label>
          <label className="floating-toolbar__config-row floating-toolbar__range-row">
            <span className="floating-toolbar__config-label">{t("chat.config.textSpeed")}</span>
            <span className="floating-toolbar__range-control">
              <input
                aria-label={t("chat.config.textSpeed")}
                className="floating-toolbar__range"
                max={runtimeTextSpeedMax}
                min={runtimeTextSpeedMin}
                onChange={handleTextSpeedChange}
                step={1}
                type="range"
                value={textSpeed}
              />
              <span className="floating-toolbar__range-value">
                {t("chat.config.textSpeedValue", { value: textSpeed })}
              </span>
            </span>
          </label>
          <label className="floating-toolbar__config-row floating-toolbar__range-row">
            <span className="floating-toolbar__config-label">{t("chat.config.dialogOpacity")}</span>
            <span className="floating-toolbar__range-control">
              <input
                aria-label={t("chat.config.dialogOpacity")}
                className="floating-toolbar__range"
                max={runtimeDialogOpacityMax}
                min={runtimeDialogOpacityMin}
                onChange={handleDialogOpacityChange}
                step={runtimeDialogOpacityStep}
                type="range"
                value={dialogOpacity}
              />
              <span className="floating-toolbar__range-value">
                {t("chat.config.dialogOpacityValue", { value: dialogOpacityPercent })}
              </span>
            </span>
          </label>
          <PluginSlot slot="chat-toolbar" />
        </div>
      </div>
    </div>
  );
}

function InputLayer({
  disabled,
  hidden,
  onChange,
  onSubmit,
  value,
}: {
  disabled: boolean;
  hidden: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  value: string;
}) {
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const transcriptBaseRef = useRef("");
  const valueRef = useRef(value);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  const stopListening = () => {
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.stop();
    }
    setListening(false);
  };

  useEffect(() => {
    if (disabled && listening) {
      stopListening();
    }
  }, [disabled, listening]);

  useEffect(
    () => () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    },
    [],
  );

  const startListening = () => {
    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      showToast({ kind: "error", message: t("chat.input.micUnsupported"), title: t("common.operationFailed") });
      return;
    }
    try {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = speechRecognitionLanguage(language);
      transcriptBaseRef.current = valueRef.current.trim();
      recognition.onresult = (event) => {
        let finalText = "";
        let interimText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          const transcript = result[0]?.transcript ?? "";
          if (result.isFinal) {
            finalText += transcript;
          } else {
            interimText += transcript;
          }
        }
        if (finalText) {
          const next = appendTranscript(transcriptBaseRef.current, finalText, language);
          transcriptBaseRef.current = next;
          onChange(next);
        } else if (interimText) {
          onChange(appendTranscript(transcriptBaseRef.current, interimText, language));
        }
      };
      recognition.onerror = (event) => {
        recognitionRef.current = null;
        setListening(false);
        const denied = event.error === "not-allowed" || event.error === "service-not-allowed";
        if (event.error !== "no-speech") {
          showToast({
            kind: "error",
            message: denied ? t("chat.input.micDenied") : event.message || event.error || t("chat.input.micError"),
            title: t("common.operationFailed"),
          });
        }
      };
      recognition.onend = () => {
        recognitionRef.current = null;
        setListening(false);
      };
      recognitionRef.current = recognition;
      recognition.start();
      setListening(true);
    } catch (error) {
      recognitionRef.current = null;
      setListening(false);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.input.micError"),
        title: t("common.operationFailed"),
      });
    }
  };

  if (hidden) {
    return null;
  }

  return (
    <div className="input-layer" data-chat-stage-hitbox="true" data-listening={listening ? "true" : "false"}>
      <TextArea
        className="input-layer__input"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder={t("chat.input.placeholder")}
        value={value}
      />
      <IconButton
        className={["input-layer__mic", listening ? "input-layer__mic--active" : ""].filter(Boolean).join(" ")}
        disabled={disabled && !listening}
        label={listening ? t("chat.input.micStop") : t("chat.input.micStart")}
        onClick={() => {
          if (listening) {
            stopListening();
          } else {
            startListening();
          }
        }}
      >
        {listening ? (
          <MicOff aria-hidden className="icon-button__icon" />
        ) : (
          <Mic aria-hidden className="icon-button__icon" />
        )}
      </IconButton>
      <Button
        disabled={!value.trim() || disabled}
        icon={<Send aria-hidden className="button__icon" />}
        onClick={onSubmit}
        variant="primary"
      >
        {t("chat.input.send")}
      </Button>
    </div>
  );
}

export function ChatStagePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(chatStageReducer, emptyChatState);
  const [confirmClearHistory, setConfirmClearHistory] = useState(false);
  const [confirmRevertUserIndex, setConfirmRevertUserIndex] = useState<number | null>(null);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState(readChatStageRuntimeConfig);
  const [tokenUsageOpen, setTokenUsageOpen] = useState(false);
  const [toolbarConfigOpen, setToolbarConfigOpen] = useState(false);
  const [toolbarOpen, setToolbarOpen] = useState(false);
  const [visibleDialogCharacters, setVisibleDialogCharacters] = useState(0);
  const { showToast } = useToast();
  const { t } = useI18n();
  const theme = useOptionalChatTheme();
  const themeStyle = theme?.style ?? {};
  const stageStyle = useMemo(
    () =>
      ({
        ...themeStyle,
        "--chat-dialog-runtime-opacity": String(runtimeConfig.dialogOpacity),
      }) as CSSProperties,
    [runtimeConfig.dialogOpacity, themeStyle],
  );
  const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);
  const standaloneDesktopWindow = isTauriDesktop() && location.pathname === "/chat-stage";
  const transparentBackground = !viewModel.backgroundPath;
  const tokenUsageVisible = tokenUsageOpen && Boolean(viewModel.tokenUsageText);
  const modalOpen = historyDialogOpen || confirmClearHistory || confirmRevertUserIndex != null;
  const clickThroughEnabled = standaloneDesktopWindow && transparentBackground && !modalOpen;
  const eventSeqRef = useRef(0);
  eventSeqRef.current = state.eventSeq;
  const pendingAnimatedDialogKeyRef = useRef<string | null>(null);
  const clickThroughIgnoredRef = useRef(false);
  const clickThroughGuardIntervalRef = useRef<number | null>(null);
  const clickThroughGuardPollingRef = useRef(false);
  const dialogSource = useMemo(
    () =>
      buildDialogTypewriterSource({
        characterName: viewModel.dialogCharacterName,
        html: viewModel.dialogHtml,
        text: viewModel.dialogText,
      }),
    [viewModel.dialogCharacterName, viewModel.dialogHtml, viewModel.dialogText],
  );
  const typewriterCps = runtimeConfig.typewriterCps ?? theme?.resolved?.typewriter.cps ?? DEFAULT_TYPEWRITER_CPS;
  const displayedDialog = useMemo(
    () => renderDialogTypewriterFrame(dialogSource, visibleDialogCharacters),
    [dialogSource, visibleDialogCharacters],
  );
  const typingDialog = visibleDialogCharacters < dialogSource.totalCharacters;

  const stopClickThroughGuard = useCallback(() => {
    if (clickThroughGuardIntervalRef.current == null) {
      return;
    }
    window.clearInterval(clickThroughGuardIntervalRef.current);
    clickThroughGuardIntervalRef.current = null;
  }, []);

  const applyClickThroughIgnored = useCallback((ignore: boolean) => {
    if (clickThroughIgnoredRef.current === ignore) {
      return;
    }
    clickThroughIgnoredRef.current = ignore;
    void setDesktopWindowClickThrough(ignore).catch((error) => {
      console.error("Desktop chat window click-through update failed", error);
    });
  }, []);

  const disableClickThrough = useCallback(() => {
    stopClickThroughGuard();
    applyClickThroughIgnored(false);
  }, [applyClickThroughIgnored, stopClickThroughGuard]);

  const startClickThroughGuard = useCallback(() => {
    if (clickThroughGuardIntervalRef.current != null) {
      return;
    }
    const pollCursor = async () => {
      if (clickThroughGuardPollingRef.current) {
        return;
      }
      clickThroughGuardPollingRef.current = true;
      try {
        const cursor = await getDesktopWindowCursorPosition();
        if (isPointInsideChatStageHitbox(cursor.x, cursor.y)) {
          disableClickThrough();
        }
      } catch (error) {
        console.error("Desktop chat window cursor guard failed", error);
        disableClickThrough();
      } finally {
        clickThroughGuardPollingRef.current = false;
      }
    };
    clickThroughGuardIntervalRef.current = window.setInterval(pollCursor, clickThroughGuardIntervalMs);
    void pollCursor();
  }, [disableClickThrough]);

  const enableClickThrough = useCallback(() => {
    applyClickThroughIgnored(true);
    startClickThroughGuard();
  }, [applyClickThroughIgnored, startClickThroughGuard]);

  const setClickThroughIgnored = useCallback(
    (ignore: boolean) => {
      if (ignore) {
        enableClickThrough();
      } else {
        disableClickThrough();
      }
    },
    [disableClickThrough, enableClickThrough],
  );

  useEffect(() => {
    if (transparentBackground) {
      document.documentElement.dataset.chatStageTransparent = "true";
      document.body.dataset.chatStageTransparent = "true";
    } else {
      delete document.documentElement.dataset.chatStageTransparent;
      delete document.body.dataset.chatStageTransparent;
    }
    return () => {
      delete document.documentElement.dataset.chatStageTransparent;
      delete document.body.dataset.chatStageTransparent;
    };
  }, [transparentBackground]);

  useEffect(() => {
    if (!standaloneDesktopWindow) {
      return;
    }
    if (!clickThroughEnabled) {
      setClickThroughIgnored(false);
    }
    return () => {
      setClickThroughIgnored(false);
    };
  }, [clickThroughEnabled, setClickThroughIgnored, standaloneDesktopWindow]);

  useEffect(
    () => () => {
      stopClickThroughGuard();
    },
    [stopClickThroughGuard],
  );

  useEffect(() => {
    if (!viewModel.layers.toolbar) {
      setToolbarOpen(false);
      setToolbarConfigOpen(false);
    }
  }, [viewModel.layers.toolbar]);

  useEffect(() => {
    if (!toolbarOpen) {
      setToolbarConfigOpen(false);
    }
  }, [toolbarOpen]);

  useEffect(() => {
    if (!viewModel.tokenUsageText) {
      setTokenUsageOpen(false);
    }
  }, [viewModel.tokenUsageText]);

  useEffect(() => {
    writeChatStageRuntimeConfig(runtimeConfig);
  }, [runtimeConfig]);

  useEffect(() => {
    let mounted = true;
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          dispatch({ snapshot, type: "hydrate" });
        }
      })
      .catch((error) => {
        dispatch({ message: error instanceof Error ? error.message : t("chat.error.loadFallback"), type: "error" });
      });
    const unsubscribe = subscribeChatEvents((event) => {
      if (event.type === "dialog.end" && event.seq > eventSeqRef.current) {
        if (!event.isSystem || event.speaker.trim()) {
          pendingAnimatedDialogKeyRef.current = buildDialogTypewriterSource({
            characterName: event.speaker,
            html: event.fullHtml,
          }).cacheKey;
          setVisibleDialogCharacters(0);
        }
      }
      dispatch({ event, type: "event" });
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, [t]);

  useEffect(() => {
    const pendingKey = pendingAnimatedDialogKeyRef.current;
    if (pendingKey === dialogSource.cacheKey) {
      pendingAnimatedDialogKeyRef.current = null;
      return;
    }
    setVisibleDialogCharacters(dialogSource.totalCharacters);
  }, [dialogSource.cacheKey, dialogSource.totalCharacters]);

  useEffect(() => {
    if (visibleDialogCharacters >= dialogSource.totalCharacters) {
      return;
    }
    const delayMs = Math.max(16, Math.round(1000 / Math.max(1, typewriterCps)));
    const timeoutId = window.setTimeout(() => {
      setVisibleDialogCharacters((current) => Math.min(dialogSource.totalCharacters, current + 1));
    }, delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [dialogSource.totalCharacters, typewriterCps, visibleDialogCharacters]);

  const refreshHistory = async () => {
    setHistoryLoading(true);
    try {
      const historyEntries = await getChatHistory();
      dispatch({ historyEntries, type: "setHistoryEntries" });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
        title: t("common.operationFailed"),
      });
    } finally {
      setHistoryLoading(false);
    }
  };

  const sendCommand = async (command: ChatCommand) => {
    if (command.type === "clear-history" && !confirmClearHistory) {
      setConfirmClearHistory(true);
      return;
    }
    try {
      const snapshot = await sendChatCommand(command);
      dispatch({ snapshot, type: "hydrate" });
      if (command.type === "copy-history") {
        showToast({ kind: "success", title: t("chat.toast.historyCopied") });
      }
      if (command.type === "open-history") {
        showToast({
          kind: "success",
          message: snapshot.openedPath || snapshot.historyPath,
          title: t("chat.toast.historyOpened"),
        });
      }
      if (command.type === "clear-history") {
        setConfirmClearHistory(false);
        showToast({ kind: "success", title: t("chat.toast.historyCleared") });
      }
    } catch (error) {
      dispatch({ status: "idle", type: "setStatus" });
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.error.commandFallback"),
        title: t("common.operationFailed"),
      });
    }
  };

  const submit = () => {
    const text = viewModel.inputDraft.trim();
    if (!text) {
      return;
    }
    dispatch({ status: "generating", type: "setStatus" });
    sendCommand({ payload: text, type: "send-message" });
  };

  const updateRuntimeTextSpeed = (typewriterCps: number) => {
    setRuntimeConfig((current) => ({ ...current, typewriterCps }));
  };

  const updateRuntimeDialogOpacity = (dialogOpacity: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogOpacity }));
  };

  const advanceDialog = () => {
    if (typingDialog) {
      setVisibleDialogCharacters(dialogSource.totalCharacters);
      return;
    }
    if (!viewModel.layers.dialog || !dialogSource.totalCharacters) {
      return;
    }
    void sendCommand({ type: "dialog-advance" });
  };

  const openHistoryDialog = () => {
    setHistoryDialogOpen(true);
    void refreshHistory();
  };

  const closeSurface = () => {
    void closeChatSurface({
      closeRuntime: closeChat,
      navigate,
      snapshot: state,
    });
  };

  const handleStagePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled) {
        return;
      }
      if (isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false);
        return;
      }
      setClickThroughIgnored(true);
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled || isChatStageHitbox(event.target)) {
        return;
      }
      setClickThroughIgnored(true);
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerLeave = useCallback(() => {
    if (standaloneDesktopWindow) {
      setClickThroughIgnored(false);
    }
  }, [setClickThroughIgnored, standaloneDesktopWindow]);

  const handleStageFocus = useCallback(
    (event: FocusEvent<HTMLElement>) => {
      if (clickThroughEnabled && isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false);
      }
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  return (
    <>
      <main
        className="chat-stage"
        data-background={transparentBackground ? "transparent" : "media"}
        data-click-through={clickThroughEnabled ? "true" : "false"}
        data-token-visible={tokenUsageVisible ? "true" : "false"}
        onFocusCapture={handleStageFocus}
        onPointerDownCapture={handleStagePointerDown}
        onPointerLeave={handleStagePointerLeave}
        onPointerMoveCapture={handleStagePointerMove}
        style={stageStyle}
      >
        <StandaloneDesktopWindowControls hidden={!standaloneDesktopWindow} />
        <StandaloneDesktopResizeHandles hidden={!standaloneDesktopWindow} />
        <BackgroundLayer
          hidden={!viewModel.layers.background}
          path={viewModel.backgroundPath}
          transparent={transparentBackground}
        />
        <CgLayer hidden={!viewModel.layers.cg} path={viewModel.cgPath} />
        <SpriteLayer hidden={!viewModel.layers.sprites} sprites={viewModel.sprites} />
        <TokenUsageLayer hidden={!tokenUsageVisible} text={viewModel.tokenUsageText} />
        <BusyLayer hidden={!viewModel.layers.busy} text={viewModel.busyText} />
        <NotificationLayer hidden={!viewModel.layers.notification} text={viewModel.notificationText} />
        <DialogLayer
          canAdvance={viewModel.layers.dialog && !typingDialog && dialogSource.totalCharacters > 0}
          characterName={viewModel.dialogCharacterName}
          hidden={!viewModel.layers.dialog}
          html={displayedDialog.html}
          onAdvance={advanceDialog}
          onSkip={typingDialog ? advanceDialog : undefined}
          text={typingDialog ? displayedDialog.text : viewModel.dialogText}
          typing={typingDialog}
        />
        <OptionsLayer
          hidden={!viewModel.layers.options}
          onSelect={(option) => sendCommand({ payload: option, type: "submit-option" })}
          options={viewModel.options}
        />
        <FloatingToolbar
          asrPaused={viewModel.status === "paused"}
          closeLabel={t(standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
          configOpen={toolbarConfigOpen}
          dialogOpacity={runtimeConfig.dialogOpacity}
          hidden={!viewModel.layers.toolbar}
          hideCloseButton={standaloneDesktopWindow}
          open={toolbarOpen}
          onCloseSurface={closeSurface}
          onCommand={sendCommand}
          onConfigOpenChange={setToolbarConfigOpen}
          onDialogOpacityChange={updateRuntimeDialogOpacity}
          onOpenChange={setToolbarOpen}
          onOpenHistory={openHistoryDialog}
          onTextSpeedChange={updateRuntimeTextSpeed}
          onTokenUsageOpenChange={setTokenUsageOpen}
          status={viewModel.statusText}
          textSpeed={typewriterCps}
          tokenUsageAvailable={Boolean(viewModel.tokenUsageText)}
          tokenUsageOpen={tokenUsageOpen}
          transportMode={viewModel.transportMode}
          transportState={viewModel.transportState}
          voiceLanguage={viewModel.voiceLanguage || "ja"}
        />
        <InputLayer
          disabled={viewModel.inputDisabled}
          hidden={!viewModel.layers.input}
          onChange={(text) => dispatch({ text, type: "setDraft" })}
          onSubmit={submit}
          value={viewModel.inputDraft}
        />
        <HistoryDialog
          entries={state.historyEntries ?? []}
          loading={historyLoading}
          onClose={() => setHistoryDialogOpen(false)}
          onRefresh={() => {
            void refreshHistory();
          }}
          onRevert={(userIndex) => setConfirmRevertUserIndex(userIndex)}
          open={historyDialogOpen}
          userDisplayName={viewModel.userDisplayName}
        />
      </main>
      <AlertDialog
        body={t("chat.clear.confirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.clear.confirmAction")}
        onCancel={() => setConfirmClearHistory(false)}
        onConfirm={() => sendCommand({ type: "clear-history" })}
        open={confirmClearHistory}
        title={t("chat.clear.confirmTitle")}
      />
      <AlertDialog
        body={t("chat.history.revertConfirmBody")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("chat.history.revertConfirmAction")}
        onCancel={() => setConfirmRevertUserIndex(null)}
        onConfirm={() => {
          if (confirmRevertUserIndex == null) {
            return;
          }
          setConfirmRevertUserIndex(null);
          setHistoryDialogOpen(false);
          void sendCommand({ payload: confirmRevertUserIndex, type: "revert-history" });
        }}
        open={confirmRevertUserIndex != null}
        title={t("chat.history.revertConfirmTitle")}
      />
    </>
  );
}
