import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type ChangeEvent,
  type FocusEvent,
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
  Lock,
  Maximize2,
  Mic,
  MicOff,
  Minus,
  RotateCcw,
  Send,
  SlidersHorizontal,
  SkipForward,
  Trash2,
  Unlock,
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
import { fileUrl } from "../../entities/files/repository";
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
const runtimeDialogScaleMin = 0.8;
const runtimeDialogScaleMax = 1.2;
const runtimeDialogScaleStep = 0.05;
const runtimeSpriteDefaultScaleKey = "__default__";
const runtimeSpriteScaleMin = 0;
const runtimeSpriteScaleMax = 3;
const runtimeSpriteScaleStep = 0.05;
const runtimeSpriteOffsetMin = -240;
const runtimeSpriteOffsetMax = 240;
const runtimeSpriteOffsetStep = 4;
const runtimeWindowScaleMin = 0.8;
const runtimeWindowScaleMax = 1.2;
const runtimeWindowScaleStep = 0.05;

interface ChatStageRuntimeConfig {
  dialogOpacity: number;
  dialogScale: number;
  spriteScales: Record<string, number>;
  spriteOffsetX: number;
  spriteOffsetY: number;
  typewriterCps: number | null;
  windowScale: number;
}

const defaultChatStageRuntimeConfig: ChatStageRuntimeConfig = {
  dialogOpacity: 1,
  dialogScale: 1,
  spriteScales: {},
  spriteOffsetX: 0,
  spriteOffsetY: 0,
  typewriterCps: null,
  windowScale: 1,
};

function clampRuntimeNumber(value: unknown, fallback: number, min: number, max: number) {
  const next = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(next)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, next));
}

function readRuntimeSpriteScales(parsed: Partial<ChatStageRuntimeConfig> & { spriteScale?: unknown }) {
  const spriteScales: Record<string, number> = {};
  const rawSpriteScales = parsed.spriteScales;
  if (rawSpriteScales && typeof rawSpriteScales === "object" && !Array.isArray(rawSpriteScales)) {
    for (const [key, value] of Object.entries(rawSpriteScales)) {
      const trimmedKey = key.trim();
      if (!trimmedKey) {
        continue;
      }
      spriteScales[trimmedKey] = clampRuntimeNumber(value, 1, runtimeSpriteScaleMin, runtimeSpriteScaleMax);
    }
  }
  if (!Object.keys(spriteScales).length && parsed.spriteScale != null) {
    spriteScales[runtimeSpriteDefaultScaleKey] = clampRuntimeNumber(
      parsed.spriteScale,
      1,
      runtimeSpriteScaleMin,
      runtimeSpriteScaleMax,
    );
  }
  return spriteScales;
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
      dialogScale: clampRuntimeNumber(
        parsed.dialogScale,
        defaultChatStageRuntimeConfig.dialogScale,
        runtimeDialogScaleMin,
        runtimeDialogScaleMax,
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
      spriteScales: readRuntimeSpriteScales(parsed),
      spriteOffsetX: Math.round(
        clampRuntimeNumber(
          parsed.spriteOffsetX,
          defaultChatStageRuntimeConfig.spriteOffsetX,
          runtimeSpriteOffsetMin,
          runtimeSpriteOffsetMax,
        ),
      ),
      spriteOffsetY: Math.round(
        clampRuntimeNumber(
          parsed.spriteOffsetY,
          defaultChatStageRuntimeConfig.spriteOffsetY,
          runtimeSpriteOffsetMin,
          runtimeSpriteOffsetMax,
        ),
      ),
      windowScale: clampRuntimeNumber(
        parsed.windowScale,
        defaultChatStageRuntimeConfig.windowScale,
        runtimeWindowScaleMin,
        runtimeWindowScaleMax,
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

function runtimeSpriteKey(sprite: ChatStageSprite, index: number) {
  return sprite.id || sprite.characterName || sprite.label || `slot-${sprite.slot ?? index}`;
}

function runtimeSpriteLabel(sprite: ChatStageSprite, index: number) {
  return sprite.label || sprite.characterName || sprite.id || `#${index + 1}`;
}

function runtimeSpriteScale(config: ChatStageRuntimeConfig, sprite: ChatStageSprite, index: number) {
  const key = runtimeSpriteKey(sprite, index);
  return config.spriteScales[key] ?? config.spriteScales[runtimeSpriteDefaultScaleKey] ?? 1;
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

function stageAssetUrl(path?: string) {
  if (!path) {
    return "";
  }
  if (/^(?:[a-z][a-z\d+.-]*:|\/assets\/)/i.test(path)) {
    return path;
  }
  return fileUrl(path);
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
  const src = stageAssetUrl(path);
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__background", hidden)}
      data-transparent={transparent ? "true" : "false"}
      hidden={hidden}
    >
      {transparent ? null : <div aria-hidden className="chat-stage__fallback" />}
      {src ? <img alt="" onError={hideBrokenStageAsset} src={src} /> : null}
    </div>
  );
}

function CgLayer({ hidden, path }: { hidden: boolean; path?: string }) {
  const src = stageAssetUrl(path);
  return (
    <div aria-hidden={hidden} className={layerClassName("chat-stage__cg", hidden)} hidden={hidden}>
      {src ? <img alt="" onError={hideBrokenStageAsset} src={src} /> : null}
    </div>
  );
}

function SpriteLayer({
  hidden,
  runtimeScaleForSprite,
  sprites,
}: {
  hidden: boolean;
  runtimeScaleForSprite: (sprite: ChatStageSprite, index: number) => number;
  sprites: ChatStageSprite[];
}) {
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
              "--sprite-offset-x": `${sprite.x ?? 0}px`,
              "--sprite-offset-y": `${sprite.y ?? 0}px`,
              "--sprite-scale": (sprite.scale ?? 1) * runtimeScaleForSprite(sprite, index),
            } as CSSProperties
          }
        >
          <img
            alt={sprite.label}
            className="sprite-layer__image"
            onError={hideBrokenStageAsset}
            src={stageAssetUrl(sprite.path)}
          />
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
        <div className="dialog-layer__body">
          <p className="dialog-layer__text" dangerouslySetInnerHTML={{ __html: html }} />
        </div>
      ) : (
        <div className="dialog-layer__body">
          <p className="dialog-layer__text">{text}</p>
        </div>
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

function TopStageTools({
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

function DialogStageControls({
  asrPaused,
  closeLabel,
  configOpen,
  hideCloseButton,
  hidden,
  locked,
  onCloseSurface,
  onCommand,
  onConfigOpenChange,
  onLockedChange,
  onOpenHistory,
  showAsrControl,
}: {
  asrPaused: boolean;
  closeLabel: string;
  configOpen: boolean;
  hidden: boolean;
  hideCloseButton: boolean;
  locked: boolean;
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

function ChatConfigDialog({
  dialogOpacity,
  dialogScale,
  onClose,
  onCommand,
  onDialogOpacityChange,
  onDialogScaleChange,
  onSpriteOffsetXChange,
  onSpriteOffsetYChange,
  onSpriteScaleChange,
  onTextSpeedChange,
  onWindowScaleChange,
  open,
  spriteOffsetX,
  spriteOffsetY,
  spriteScales,
  sprites,
  textSpeed,
  voiceLanguage,
  windowScale,
}: {
  dialogOpacity: number;
  dialogScale: number;
  onClose: () => void;
  onCommand: (command: ChatCommand) => void;
  onDialogOpacityChange: (value: number) => void;
  onDialogScaleChange: (value: number) => void;
  onSpriteOffsetXChange: (value: number) => void;
  onSpriteOffsetYChange: (value: number) => void;
  onSpriteScaleChange: (spriteKey: string, value: number) => void;
  onTextSpeedChange: (value: number) => void;
  onWindowScaleChange: (value: number) => void;
  open: boolean;
  spriteOffsetX: number;
  spriteOffsetY: number;
  spriteScales: Record<string, number>;
  sprites: ChatStageSprite[];
  textSpeed: number;
  voiceLanguage: string;
  windowScale: number;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const dialogOpacityPercent = Math.round(dialogOpacity * 100);
  const dialogScalePercent = Math.round(dialogScale * 100);
  const windowScalePercent = Math.round(windowScale * 100);

  if (!open) {
    return null;
  }

  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
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
  const handleDialogScaleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onDialogScaleChange(
      clampRuntimeNumber(event.target.value, dialogScale, runtimeDialogScaleMin, runtimeDialogScaleMax),
    );
  };
  const handleSpriteOffsetXChange = (event: ChangeEvent<HTMLInputElement>) => {
    onSpriteOffsetXChange(
      Math.round(clampRuntimeNumber(event.target.value, spriteOffsetX, runtimeSpriteOffsetMin, runtimeSpriteOffsetMax)),
    );
  };
  const handleSpriteOffsetYChange = (event: ChangeEvent<HTMLInputElement>) => {
    onSpriteOffsetYChange(
      Math.round(clampRuntimeNumber(event.target.value, spriteOffsetY, runtimeSpriteOffsetMin, runtimeSpriteOffsetMax)),
    );
  };
  const handleWindowScaleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onWindowScaleChange(
      clampRuntimeNumber(event.target.value, windowScale, runtimeWindowScaleMin, runtimeWindowScaleMax),
    );
  };

  return (
    <div
      className="chat-config-backdrop"
      data-chat-stage-hitbox="true"
      onMouseDown={handleBackdropMouseDown}
      role="presentation"
    >
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="chat-config-dialog"
        id="chat-stage-dialog-config"
        onKeyDown={handleKeyDown}
        role="dialog"
      >
        <header className="chat-config-dialog__header">
          <div className="chat-config-dialog__heading">
            <p className="chat-config-dialog__eyebrow">CONFIG</p>
            <h2 className="chat-config-dialog__title" id={titleId}>
              {t("chat.toolbar.config")}
            </h2>
          </div>
          <IconButton className="chat-config-dialog__close" label={t("common.close")} onClick={onClose}>
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </header>
        <div className="chat-config-dialog__body">
          <section className="chat-config-dialog__section">
            <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionConversation")}</h3>
            <label className="chat-config-dialog__row chat-config-dialog__voice">
              <span className="chat-config-dialog__label">
                <Languages aria-hidden className="chat-config-dialog__voice-icon" />
                {t("template.field.voiceLanguage")}
              </span>
              <Select
                aria-label={t("template.field.voiceLanguage")}
                className="chat-config-dialog__voice-select"
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
            <label className="chat-config-dialog__row chat-config-dialog__range-row">
              <span className="chat-config-dialog__label">{t("chat.config.textSpeed")}</span>
              <span className="chat-config-dialog__range-control">
                <input
                  aria-label={t("chat.config.textSpeed")}
                  className="chat-config-dialog__range"
                  max={runtimeTextSpeedMax}
                  min={runtimeTextSpeedMin}
                  onChange={handleTextSpeedChange}
                  step={1}
                  type="range"
                  value={textSpeed}
                />
                <span className="chat-config-dialog__range-value">
                  {t("chat.config.textSpeedValue", { value: textSpeed })}
                </span>
              </span>
            </label>
          </section>

          <section className="chat-config-dialog__section">
            <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionLayout")}</h3>
            <label className="chat-config-dialog__row chat-config-dialog__range-row">
              <span className="chat-config-dialog__label">{t("chat.config.windowScale")}</span>
              <span className="chat-config-dialog__range-control">
                <input
                  aria-label={t("chat.config.windowScale")}
                  className="chat-config-dialog__range"
                  max={runtimeWindowScaleMax}
                  min={runtimeWindowScaleMin}
                  onChange={handleWindowScaleChange}
                  step={runtimeWindowScaleStep}
                  type="range"
                  value={windowScale}
                />
                <span className="chat-config-dialog__range-value">
                  {t("chat.config.scaleValue", { value: windowScalePercent })}
                </span>
              </span>
            </label>
            <label className="chat-config-dialog__row chat-config-dialog__range-row">
              <span className="chat-config-dialog__label">{t("chat.config.dialogScale")}</span>
              <span className="chat-config-dialog__range-control">
                <input
                  aria-label={t("chat.config.dialogScale")}
                  className="chat-config-dialog__range"
                  max={runtimeDialogScaleMax}
                  min={runtimeDialogScaleMin}
                  onChange={handleDialogScaleChange}
                  step={runtimeDialogScaleStep}
                  type="range"
                  value={dialogScale}
                />
                <span className="chat-config-dialog__range-value">
                  {t("chat.config.scaleValue", { value: dialogScalePercent })}
                </span>
              </span>
            </label>
            <label className="chat-config-dialog__row chat-config-dialog__range-row">
              <span className="chat-config-dialog__label">{t("chat.config.dialogOpacity")}</span>
              <span className="chat-config-dialog__range-control">
                <input
                  aria-label={t("chat.config.dialogOpacity")}
                  className="chat-config-dialog__range"
                  max={runtimeDialogOpacityMax}
                  min={runtimeDialogOpacityMin}
                  onChange={handleDialogOpacityChange}
                  step={runtimeDialogOpacityStep}
                  type="range"
                  value={dialogOpacity}
                />
                <span className="chat-config-dialog__range-value">
                  {t("chat.config.dialogOpacityValue", { value: dialogOpacityPercent })}
                </span>
              </span>
            </label>
          </section>

          <section className="chat-config-dialog__section">
            <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionSprites")}</h3>
            {sprites.length ? (
              <div className="chat-config-dialog__sprite-list">
                {sprites.map((sprite, index) => {
                  const spriteKey = runtimeSpriteKey(sprite, index);
                  const spriteLabel = runtimeSpriteLabel(sprite, index);
                  const value = spriteScales[spriteKey] ?? spriteScales[runtimeSpriteDefaultScaleKey] ?? 1;
                  return (
                    <label className="chat-config-dialog__row chat-config-dialog__range-row" key={spriteKey}>
                      <span className="chat-config-dialog__label">{spriteLabel}</span>
                      <span className="chat-config-dialog__range-control">
                        <input
                          aria-label={`${t("chat.config.spriteScale")}: ${spriteLabel}`}
                          className="chat-config-dialog__range"
                          max={runtimeSpriteScaleMax}
                          min={runtimeSpriteScaleMin}
                          onChange={(event) =>
                            onSpriteScaleChange(
                              spriteKey,
                              clampRuntimeNumber(
                                event.target.value,
                                value,
                                runtimeSpriteScaleMin,
                                runtimeSpriteScaleMax,
                              ),
                            )
                          }
                          step={runtimeSpriteScaleStep}
                          type="range"
                          value={value}
                        />
                        <span className="chat-config-dialog__range-value">
                          {t("chat.config.scaleValue", { value: Math.round(value * 100) })}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <p className="chat-config-dialog__empty">{t("chat.config.spriteEmpty")}</p>
            )}
            <label className="chat-config-dialog__row chat-config-dialog__range-row">
              <span className="chat-config-dialog__label">{t("chat.config.spriteOffsetX")}</span>
              <span className="chat-config-dialog__range-control">
                <input
                  aria-label={t("chat.config.spriteOffsetX")}
                  className="chat-config-dialog__range"
                  max={runtimeSpriteOffsetMax}
                  min={runtimeSpriteOffsetMin}
                  onChange={handleSpriteOffsetXChange}
                  step={runtimeSpriteOffsetStep}
                  type="range"
                  value={spriteOffsetX}
                />
                <span className="chat-config-dialog__range-value">
                  {t("chat.config.spriteOffsetValue", { value: spriteOffsetX })}
                </span>
              </span>
            </label>
            <label className="chat-config-dialog__row chat-config-dialog__range-row">
              <span className="chat-config-dialog__label">{t("chat.config.spriteOffsetY")}</span>
              <span className="chat-config-dialog__range-control">
                <input
                  aria-label={t("chat.config.spriteOffsetY")}
                  className="chat-config-dialog__range"
                  max={runtimeSpriteOffsetMax}
                  min={runtimeSpriteOffsetMin}
                  onChange={handleSpriteOffsetYChange}
                  step={runtimeSpriteOffsetStep}
                  type="range"
                  value={spriteOffsetY}
                />
                <span className="chat-config-dialog__range-value">
                  {t("chat.config.spriteOffsetValue", { value: spriteOffsetY })}
                </span>
              </span>
            </label>
          </section>

          <PluginSlot slot="chat-toolbar" />
        </div>
      </section>
    </div>
  );
}

function InputLayer({
  asrPaused,
  disabled,
  hidden,
  onChange,
  onCommand,
  onSubmit,
  value,
}: {
  asrPaused: boolean;
  disabled: boolean;
  hidden: boolean;
  onChange: (value: string) => void;
  onCommand: (command: ChatCommand) => void;
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
      <div className="input-layer__voice-stack" role="group">
        <IconButton
          className={["input-layer__voice-button", "input-layer__mic", listening ? "input-layer__mic--active" : ""]
            .filter(Boolean)
            .join(" ")}
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
        <IconButton
          aria-pressed={asrPaused}
          className={[
            "input-layer__voice-button",
            "input-layer__asr-toggle",
            asrPaused ? "input-layer__asr-toggle--paused" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          label={asrPaused ? t("chat.toolbar.resumeAsr") : t("chat.toolbar.pauseAsr")}
          onClick={() => onCommand({ type: asrPaused ? "resume-asr" : "pause-asr" })}
        >
          {asrPaused ? (
            <Mic aria-hidden className="icon-button__icon" />
          ) : (
            <MicOff aria-hidden className="icon-button__icon" />
          )}
        </IconButton>
      </div>
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
  const [dialogControlsLocked, setDialogControlsLocked] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState(readChatStageRuntimeConfig);
  const [tokenUsageOpen, setTokenUsageOpen] = useState(false);
  const [toolbarConfigOpen, setToolbarConfigOpen] = useState(false);
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
        "--chat-dialog-runtime-scale": String(runtimeConfig.dialogScale),
        "--chat-dialog-runtime-width": `${Math.round(1040 * runtimeConfig.windowScale)}px`,
        "--chat-sprite-runtime-offset-x": `${runtimeConfig.spriteOffsetX}px`,
        "--chat-sprite-runtime-offset-y": `${runtimeConfig.spriteOffsetY}px`,
        "--chat-ui-runtime-width": `${Math.round(1120 * runtimeConfig.windowScale)}px`,
        "--chat-ui-window-scale": String(runtimeConfig.windowScale),
      }) as CSSProperties,
    [
      runtimeConfig.dialogOpacity,
      runtimeConfig.dialogScale,
      runtimeConfig.spriteOffsetX,
      runtimeConfig.spriteOffsetY,
      runtimeConfig.windowScale,
      themeStyle,
    ],
  );
  const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);
  const standaloneDesktopWindow = isTauriDesktop() && location.pathname === "/chat-stage";
  const transparentBackground = !viewModel.backgroundPath;
  const tokenUsageVisible = tokenUsageOpen && Boolean(viewModel.tokenUsageText);
  const modalOpen = toolbarConfigOpen || historyDialogOpen || confirmClearHistory || confirmRevertUserIndex != null;
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
    if (!viewModel.layers.dialog) {
      setToolbarConfigOpen(false);
    }
  }, [viewModel.layers.dialog]);

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

  const updateRuntimeDialogScale = (dialogScale: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogScale }));
  };

  const updateRuntimeSpriteOffsetX = (spriteOffsetX: number) => {
    setRuntimeConfig((current) => ({ ...current, spriteOffsetX }));
  };

  const updateRuntimeSpriteOffsetY = (spriteOffsetY: number) => {
    setRuntimeConfig((current) => ({ ...current, spriteOffsetY }));
  };

  const updateRuntimeSpriteScale = (spriteKey: string, spriteScale: number) => {
    setRuntimeConfig((current) => ({
      ...current,
      spriteScales: {
        ...current.spriteScales,
        [spriteKey]: spriteScale,
      },
    }));
  };

  const updateRuntimeWindowScale = (windowScale: number) => {
    setRuntimeConfig((current) => ({ ...current, windowScale }));
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
        <StandaloneDesktopResizeHandles hidden={!standaloneDesktopWindow} />
        <TopStageTools
          hidden={!viewModel.layers.toolbar}
          onTokenUsageOpenChange={setTokenUsageOpen}
          standaloneDesktopWindow={standaloneDesktopWindow}
          status={viewModel.statusText}
          tokenUsageAvailable={Boolean(viewModel.tokenUsageText)}
          tokenUsageOpen={tokenUsageOpen}
          transportMode={viewModel.transportMode}
          transportState={viewModel.transportState}
        />
        <BackgroundLayer
          hidden={!viewModel.layers.background}
          path={viewModel.backgroundPath}
          transparent={transparentBackground}
        />
        <CgLayer hidden={!viewModel.layers.cg} path={viewModel.cgPath} />
        <SpriteLayer
          hidden={!viewModel.layers.sprites}
          runtimeScaleForSprite={(sprite, index) => runtimeSpriteScale(runtimeConfig, sprite, index)}
          sprites={viewModel.sprites}
        />
        <TokenUsageLayer hidden={!tokenUsageVisible} text={viewModel.tokenUsageText} />
        <BusyLayer hidden={!viewModel.layers.busy} text={viewModel.busyText} />
        <NotificationLayer hidden={!viewModel.layers.notification} text={viewModel.notificationText} />
        <div
          aria-hidden={!viewModel.layers.dialog}
          className={layerClassName("dialog-stack", !viewModel.layers.dialog)}
          hidden={!viewModel.layers.dialog}
        >
          <DialogStageControls
            asrPaused={viewModel.status === "paused"}
            closeLabel={t(standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
            configOpen={toolbarConfigOpen}
            hidden={!viewModel.layers.dialog}
            hideCloseButton={standaloneDesktopWindow}
            locked={dialogControlsLocked}
            onCloseSurface={closeSurface}
            onCommand={sendCommand}
            onConfigOpenChange={setToolbarConfigOpen}
            onLockedChange={setDialogControlsLocked}
            onOpenHistory={openHistoryDialog}
            showAsrControl={!viewModel.layers.input && viewModel.status === "paused"}
          />
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
        </div>
        <OptionsLayer
          hidden={!viewModel.layers.options}
          onSelect={(option) => sendCommand({ payload: option, type: "submit-option" })}
          options={viewModel.options}
        />
        <InputLayer
          asrPaused={viewModel.status === "paused"}
          disabled={viewModel.inputDisabled}
          hidden={!viewModel.layers.input}
          onChange={(text) => dispatch({ text, type: "setDraft" })}
          onCommand={sendCommand}
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
        <ChatConfigDialog
          dialogOpacity={runtimeConfig.dialogOpacity}
          dialogScale={runtimeConfig.dialogScale}
          onClose={() => setToolbarConfigOpen(false)}
          onCommand={sendCommand}
          onDialogOpacityChange={updateRuntimeDialogOpacity}
          onDialogScaleChange={updateRuntimeDialogScale}
          onSpriteOffsetXChange={updateRuntimeSpriteOffsetX}
          onSpriteOffsetYChange={updateRuntimeSpriteOffsetY}
          onSpriteScaleChange={updateRuntimeSpriteScale}
          onTextSpeedChange={updateRuntimeTextSpeed}
          onWindowScaleChange={updateRuntimeWindowScale}
          open={toolbarConfigOpen}
          spriteOffsetX={runtimeConfig.spriteOffsetX}
          spriteOffsetY={runtimeConfig.spriteOffsetY}
          spriteScales={runtimeConfig.spriteScales}
          sprites={viewModel.sprites}
          textSpeed={typewriterCps}
          voiceLanguage={viewModel.voiceLanguage || "ja"}
          windowScale={runtimeConfig.windowScale}
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
