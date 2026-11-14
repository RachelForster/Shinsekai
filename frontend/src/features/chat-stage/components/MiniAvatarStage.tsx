import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type FocusEvent,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Check,
  FileText,
  ImagePlus,
  Keyboard,
  LoaderCircle,
  Maximize2,
  MessageSquare,
  Mic,
  MicOff,
  MonitorOff,
  MonitorUp,
  Play,
  Plus,
  Send,
  UserRound,
  X,
} from "lucide-react";

import {
  CharacterVisual,
  STATIC_AVATAR_TYPE,
  normalizeVisualFraming,
  visualFramingMinRatio,
  type VisualFraming,
} from "../../../modules/character-visual";
import { startDesktopWindowDrag, type DesktopMiniDockSide } from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import type {
  ChatAttachmentInput,
  ChatCommand,
  ChatOption,
  ChatToolConfirmation,
} from "../../../shared/platform/types";
import { IconButton, TextInput } from "../../../shared/ui";
import { classNames, hideBrokenStageAsset, stageAssetUrl } from "../chatStageUtils";
import { useDismissableLayer } from "../hooks/useDismissableLayer";
import { chatStageSpriteCharacterName } from "../state/sprites";
import type { ChatStageSprite, ChatStageSpriteReaction } from "../state/types";

export const MINI_AVATAR_HOVER_HIDE_MS = 260;
export const MINI_AVATAR_IDLE_BUBBLE_HIDE_MS = 8000;
const MINI_AVATAR_DRAG_THRESHOLD_PX = 5;
const MINI_AVATAR_STATIC_FRAMING: Readonly<VisualFraming> = { heightRatio: 0.74, verticalPosition: 0.16 };
const MINI_AVATAR_MODEL_FRAMING: Readonly<VisualFraming> = { heightRatio: 0.32, verticalPosition: 0.06 };

function composeMiniAvatarFraming(baseFraming: VisualFraming, runtimeFraming?: VisualFraming): VisualFraming {
  const userFraming = normalizeVisualFraming(runtimeFraming);
  if (userFraming.heightRatio >= 1) {
    return baseFraming;
  }
  const userTop = (1 - userFraming.heightRatio) * userFraming.verticalPosition;
  const heightRatio = Math.max(visualFramingMinRatio, userFraming.heightRatio * baseFraming.heightRatio);
  const top = Math.min(
    1 - heightRatio,
    userTop + Math.max(0, userFraming.heightRatio - heightRatio) * baseFraming.verticalPosition,
  );
  return {
    heightRatio,
    verticalPosition: heightRatio < 1 ? Math.min(1, Math.max(0, top / (1 - heightRatio))) : 0,
  };
}

function speakerNameFallback(resolvedName: string, dialogCharacterName?: string, userDisplayName?: string): string {
  if (resolvedName) {
    return resolvedName;
  }
  const candidate = dialogCharacterName?.trim() ?? "";
  return candidate && candidate !== (userDisplayName ?? "").trim() ? candidate : "";
}

export function resolveMiniAvatarSpeaker({
  dialogCharacterName,
  previousSpeakerName,
  sprites,
  thinkingCharacterName,
  userDisplayName,
}: {
  dialogCharacterName?: string;
  previousSpeakerName?: string;
  sprites: readonly ChatStageSprite[];
  thinkingCharacterName?: string;
  userDisplayName?: string;
}): { speakerName: string; sprite?: ChatStageSprite } {
  const user = (userDisplayName ?? "").trim();
  const findSpriteByName = (candidate?: string) => {
    const trimmed = candidate?.trim() ?? "";
    if (!trimmed || trimmed === user) {
      return undefined;
    }
    return sprites.find((sprite) => chatStageSpriteCharacterName(sprite) === trimmed);
  };

  const dialogSprite = findSpriteByName(dialogCharacterName);
  if (dialogSprite) {
    return { speakerName: chatStageSpriteCharacterName(dialogSprite), sprite: dialogSprite };
  }

  const thinkingSprite = findSpriteByName(thinkingCharacterName);
  if (thinkingSprite) {
    return { speakerName: chatStageSpriteCharacterName(thinkingSprite), sprite: thinkingSprite };
  }

  const previousSprite = findSpriteByName(previousSpeakerName);
  if (previousSprite) {
    return { speakerName: chatStageSpriteCharacterName(previousSprite), sprite: previousSprite };
  }

  const latestSprite = sprites.at(-1);
  if (latestSprite) {
    return { speakerName: chatStageSpriteCharacterName(latestSprite), sprite: latestSprite };
  }

  const fallbackName =
    [dialogCharacterName, thinkingCharacterName, previousSpeakerName]
      .map((name) => name?.trim() ?? "")
      .find((name) => name.length > 0 && name !== user) ?? "";

  return { speakerName: fallbackName, sprite: undefined };
}

export function MiniAvatarStage({
  asrEnabled,
  asrLoading,
  asrRunning,
  attachments,
  autoPlay = false,
  batchEnabled,
  busyText,
  canAdvance,
  dialogCharacterName,
  dialogText,
  dialogVisible,
  dockSide,
  inputDisabled,
  inputValue,
  locked = false,
  longPressTalk = false,
  notificationText,
  notificationVisible,
  onAdvance,
  onAutoPlayChange,
  onChangeInput,
  onCommand,
  onDesktopDragEnd,
  onDropFiles,
  onExitMiniMode,
  onFlushBatch,
  onInputActivity,
  onLongPressTalkChange,
  onPickAttachments,
  onRemoveAttachment,
  onResolveToolConfirmation,
  onSelectOption,
  onSubmit,
  onToggleScreenShare,
  options,
  optionsVisible,
  previousMessages,
  runtimeFramingForSprite,
  screenShareStarting = false,
  screenSharing = false,
  spriteReaction,
  sprites,
  standaloneDesktopWindow,
  status,
  submitDisabled = false,
  thinkingCharacterName,
  toolConfirmation,
  typing,
  userDisplayName,
}: {
  asrEnabled: boolean;
  asrLoading: boolean;
  asrRunning: boolean;
  attachments: ChatAttachmentInput[];
  autoPlay?: boolean;
  batchEnabled: boolean;
  busyText?: string;
  canAdvance: boolean;
  dialogCharacterName?: string;
  dialogText: string;
  dialogVisible: boolean;
  dockSide: DesktopMiniDockSide;
  inputDisabled: boolean;
  inputValue: string;
  locked?: boolean;
  longPressTalk?: boolean;
  notificationText?: string;
  notificationVisible: boolean;
  onAdvance: () => void;
  onAutoPlayChange?: (value: boolean) => void;
  onChangeInput: (value: string) => void;
  onCommand: (command: ChatCommand) => void | Promise<void>;
  onDesktopDragEnd?: () => void;
  onDropFiles?: (files: File[]) => void | Promise<void>;
  onExitMiniMode: () => void;
  onFlushBatch: () => void | Promise<void>;
  onInputActivity: (state: { composing: boolean; hasText: boolean }) => void;
  onLongPressTalkChange?: (value: boolean) => void;
  onPickAttachments: (kind: ChatAttachmentInput["kind"]) => void;
  onRemoveAttachment: (attachment: ChatAttachmentInput) => void;
  onResolveToolConfirmation: (action: "confirm" | "cancel") => void;
  onSelectOption: (option: ChatOption) => void;
  onSubmit: (textOverride?: string) => void | Promise<void>;
  onToggleScreenShare?: () => void;
  options: ChatOption[];
  optionsVisible: boolean;
  previousMessages: string[];
  runtimeFramingForSprite?: (sprite: ChatStageSprite, index: number) => VisualFraming;
  screenShareStarting?: boolean;
  screenSharing?: boolean;
  spriteReaction?: ChatStageSpriteReaction | null;
  sprites: readonly ChatStageSprite[];
  standaloneDesktopWindow: boolean;
  status: string;
  submitDisabled?: boolean;
  thinkingCharacterName?: string;
  toolConfirmation?: ChatToolConfirmation | null;
  typing: boolean;
  userDisplayName: string;
}) {
  const { t } = useI18n();
  const [hovered, setHovered] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);
  const [hoverBubblePreview, setHoverBubblePreview] = useState(false);
  const [inputPinned, setInputPinned] = useState(false);
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [idleDismissed, setIdleDismissed] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [webOffset, setWebOffset] = useState({ x: 0, y: 0 });
  const [webDockSide, setWebDockSide] = useState<DesktopMiniDockSide>("right");
  const [failedSpriteAssetKey, setFailedSpriteAssetKey] = useState("");

  const previousSpeakerRef = useRef<string>("");
  const hoverHideTimerRef = useRef<number | null>(null);
  const plusRootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const historyIndexRef = useRef(-1);
  const inputActivityRef = useRef("");
  const dragSessionRef = useRef<{
    active: boolean;
    dragged: boolean;
    originX: number;
    originY: number;
    pointerId: number;
    startX: number;
    startY: number;
  } | null>(null);
  const suppressNextClickRef = useRef(false);

  const resolvedSpeaker = useMemo(
    () =>
      resolveMiniAvatarSpeaker({
        dialogCharacterName,
        previousSpeakerName: previousSpeakerRef.current,
        sprites,
        thinkingCharacterName,
        userDisplayName,
      }),
    [dialogCharacterName, sprites, thinkingCharacterName, userDisplayName],
  );

  useEffect(() => {
    if (resolvedSpeaker.speakerName) {
      previousSpeakerRef.current = resolvedSpeaker.speakerName;
    }
  }, [resolvedSpeaker.speakerName]);

  const effectiveDockSide = standaloneDesktopWindow ? dockSide : webDockSide;
  const closePlusMenu = useCallback(() => setPlusMenuOpen(false), []);
  useDismissableLayer({ active: plusMenuOpen, onDismiss: closePlusMenu, rootRef: plusRootRef });

  useEffect(() => {
    if (attachments.length > 0) {
      setInputPinned(true);
    }
  }, [attachments.length]);

  useEffect(() => {
    if (!inputValue.trim()) {
      inputActivityRef.current = "false:false";
    }
  }, [inputValue]);

  useEffect(() => {
    historyIndexRef.current = -1;
  }, [previousMessages]);

  const clearHoverTimer = useCallback(() => {
    if (hoverHideTimerRef.current != null) {
      window.clearTimeout(hoverHideTimerRef.current);
      hoverHideTimerRef.current = null;
    }
  }, []);

  useEffect(() => clearHoverTimer, [clearHoverTimer]);

  const handleHubPointerEnter = useCallback(() => {
    clearHoverTimer();
    setHovered(true);
    onDesktopDragEnd?.();
  }, [clearHoverTimer, onDesktopDragEnd]);

  const handleHubPointerLeave = useCallback(() => {
    clearHoverTimer();
    hoverHideTimerRef.current = window.setTimeout(() => {
      hoverHideTimerRef.current = null;
      setHovered(false);
      setHoverBubblePreview(false);
    }, MINI_AVATAR_HOVER_HIDE_MS);
  }, [clearHoverTimer]);

  const handleHubFocus = useCallback(() => {
    clearHoverTimer();
    setFocusWithin(true);
  }, [clearHoverTimer]);

  const handleHubBlur = useCallback((event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setFocusWithin(false);
    }
  }, []);

  const isThinking = status === "generating" || status === "initializing";
  const isSpeaking = status === "speaking" || status === "streaming" || typing;
  const ringState = isSpeaking ? "speaking" : isThinking ? "thinking" : asrRunning ? "listening" : "idle";
  const showLiveAsrDraft = asrRunning && Boolean(inputValue.trim());
  const inputVisible = inputPinned || showLiveAsrDraft;
  const trimmedDialog = dialogText.trim();
  const reactionText = spriteReaction?.text?.trim() ?? "";

  const contentSignature = `${resolvedSpeaker.speakerName}\0${trimmedDialog}\0${status}\0${notificationText ?? ""}\0${spriteReaction?.seq ?? 0}`;
  useEffect(() => {
    setIdleDismissed(false);
  }, [contentSignature]);

  const canAutoDismissBubble =
    status === "idle" &&
    !typing &&
    !canAdvance &&
    !optionsVisible &&
    !toolConfirmation &&
    !notificationVisible &&
    !hovered &&
    !hoverBubblePreview &&
    Boolean(trimmedDialog || reactionText);

  useEffect(() => {
    if (!canAutoDismissBubble || idleDismissed) {
      return;
    }
    const timer = window.setTimeout(() => {
      setIdleDismissed(true);
    }, MINI_AVATAR_IDLE_BUBBLE_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [canAutoDismissBubble, idleDismissed]);

  const hasInteractiveOptions = optionsVisible && options.length > 0;
  const bubbleVisible =
    Boolean(toolConfirmation) ||
    hasInteractiveOptions ||
    isThinking ||
    (notificationVisible && Boolean(notificationText?.trim())) ||
    (dialogVisible && Boolean(trimmedDialog) && (!idleDismissed || hoverBubblePreview)) ||
    (!dialogVisible && Boolean(reactionText) && (!idleDismissed || hoverBubblePreview));

  const controlsVisible = hovered || focusWithin || plusMenuOpen;

  const focusInputSoon = useCallback(() => {
    window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  }, []);

  const handleToggleInputPinned = () => {
    setPlusMenuOpen(false);
    setInputPinned((current) => {
      const next = !current;
      if (next) {
        focusInputSoon();
      }
      return next;
    });
  };

  const reportInputActivity = (nextValue: string, composing: boolean) => {
    if (!batchEnabled) {
      return;
    }
    const activity = { composing, hasText: Boolean(nextValue.trim()) };
    const key = `${activity.hasText}:${activity.composing}`;
    if (inputActivityRef.current === key) {
      return;
    }
    inputActivityRef.current = key;
    onInputActivity(activity);
  };

  const handleInputChange = (nextValue: string) => {
    historyIndexRef.current = -1;
    onChangeInput(nextValue);
    reportInputActivity(nextValue, false);
  };

  const recallPreviousMessage = () => {
    if (!previousMessages.length || (inputValue && historyIndexRef.current < 0)) {
      return false;
    }
    historyIndexRef.current = (historyIndexRef.current + 1) % previousMessages.length;
    const previousMessage = previousMessages[historyIndexRef.current]!;
    onChangeInput(previousMessage);
    reportInputActivity(previousMessage, false);
    return true;
  };

  const canSubmit = Boolean(inputValue.trim() || attachments.length) && !inputDisabled && !submitDisabled && !locked;

  const submitKeepingExpanded = async (flushBatch = false) => {
    if (!canSubmit) {
      return;
    }
    await onSubmit();
    if (flushBatch && batchEnabled) {
      await onFlushBatch();
    }
    focusInputSoon();
  };

  const toggleAsr = () => {
    void onCommand({ type: asrEnabled ? "pause-asr" : "resume-asr" });
  };

  const handleAvatarPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) {
      return;
    }
    dragSessionRef.current = {
      active: true,
      dragged: false,
      originX: webOffset.x,
      originY: webOffset.y,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
    };
    if (!standaloneDesktopWindow && typeof event.currentTarget.setPointerCapture === "function") {
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Synthetic pointer events in unit tests may not have an active pointer id.
      }
    }
  };

  const handleAvatarPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const session = dragSessionRef.current;
    if (!session || !session.active || session.pointerId !== event.pointerId) {
      return;
    }
    const dx = event.clientX - session.startX;
    const dy = event.clientY - session.startY;
    if (!session.dragged && Math.hypot(dx, dy) >= MINI_AVATAR_DRAG_THRESHOLD_PX) {
      session.dragged = true;
      suppressNextClickRef.current = true;
      if (standaloneDesktopWindow) {
        session.active = false;
        void startDesktopWindowDrag()
          .then(() => {
            onDesktopDragEnd?.();
          })
          .catch((error) => {
            console.error("Desktop mini avatar drag failed", error);
          });
        return;
      }
    }
    if (session.dragged && !standaloneDesktopWindow) {
      const nextX = session.originX + dx;
      const nextY = session.originY + dy;
      setWebOffset({ x: nextX, y: nextY });
      if (typeof window !== "undefined" && window.innerWidth > 0) {
        setWebDockSide(event.clientX / window.innerWidth >= 0.6 ? "right" : "left");
      }
    }
  };

  const finishAvatarPointer = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const session = dragSessionRef.current;
    if (!session || session.pointerId !== event.pointerId) {
      return;
    }
    dragSessionRef.current = null;
  };

  const handleAvatarClick = () => {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false;
      return;
    }
    if (typing || canAdvance) {
      onAdvance();
      return;
    }
    if (idleDismissed && (trimmedDialog || reactionText)) {
      setIdleDismissed(false);
    }
  };

  const handleAvatarDoubleClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onExitMiniMode();
  };

  const handleBubbleClick = (event: MouseEvent<HTMLElement>) => {
    if (
      event.target instanceof Element &&
      event.target.closest("button, a, input, textarea, select, [role='button']")
    ) {
      return;
    }
    if (toolConfirmation || hasInteractiveOptions || isThinking) {
      return;
    }
    if (typing || canAdvance) {
      onAdvance();
      return;
    }
    setIdleDismissed(true);
    setHoverBubblePreview(false);
  };

  const canDropFiles = Boolean(onDropFiles) && !inputDisabled && !locked;
  const handleDragOver = (event: DragEvent<HTMLElement>) => {
    if (!canDropFiles || !Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }
    event.preventDefault();
    setDragActive(true);
  };
  const handleDragLeave = (event: DragEvent<HTMLElement>) => {
    if (event.currentTarget === event.target) {
      setDragActive(false);
    }
  };
  const handleDrop = (event: DragEvent<HTMLElement>) => {
    if (!canDropFiles) {
      return;
    }
    event.preventDefault();
    setDragActive(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length) {
      setInputPinned(true);
      void onDropFiles?.(files);
      focusInputSoon();
    }
  };

  const activeSprite = resolvedSpeaker.sprite;
  const activeSpriteIndex = activeSprite ? sprites.indexOf(activeSprite) : -1;
  const activeAvatarType = (activeSprite?.avatarType ?? STATIC_AVATAR_TYPE).trim().toLowerCase() || STATIC_AVATAR_TYPE;
  const activeSpriteAssetKey = activeSprite
    ? `${activeAvatarType}:${activeSprite.path ?? ""}:${activeSprite.modelUrl ?? ""}`
    : "";
  const canRenderVisualAsset = Boolean(
    activeSprite &&
    (activeAvatarType === STATIC_AVATAR_TYPE ? activeSprite.path : activeSprite.modelUrl) &&
    activeSpriteAssetKey !== failedSpriteAssetKey,
  );
  const activeCharacterKey = activeSprite ? chatStageSpriteCharacterName(activeSprite) || activeSprite.id : "";
  const activeVoiceCharacterName = activeSprite
    ? chatStageSpriteCharacterName(activeSprite) ||
      speakerNameFallback(resolvedSpeaker.speakerName, dialogCharacterName, userDisplayName)
    : "";
  const activeFraming = composeMiniAvatarFraming(
    activeAvatarType === STATIC_AVATAR_TYPE ? MINI_AVATAR_STATIC_FRAMING : MINI_AVATAR_MODEL_FRAMING,
    activeSprite && activeSpriteIndex >= 0 ? runtimeFramingForSprite?.(activeSprite, activeSpriteIndex) : undefined,
  );
  const speakerLabel = speakerNameFallback(resolvedSpeaker.speakerName, dialogCharacterName, userDisplayName);
  const speakerInitial = Array.from(speakerLabel)[0] ?? "";
  const asrLabel = t(asrEnabled ? "chat.toolbar.pauseAsr" : "chat.toolbar.resumeAsr");
  const asrIcon = asrLoading ? (
    <LoaderCircle aria-hidden className="icon-button__icon input-layer__asr-spinner" />
  ) : asrEnabled ? (
    <MicOff aria-hidden className="icon-button__icon" />
  ) : (
    <Mic aria-hidden className="icon-button__icon" />
  );

  const anchorStyle = standaloneDesktopWindow
    ? undefined
    : ({
        "--mini-web-offset-x": `${webOffset.x}px`,
        "--mini-web-offset-y": `${webOffset.y}px`,
      } as CSSProperties);

  const bubbleHint = toolConfirmation
    ? t("chat.toolConfirmation.label")
    : hasInteractiveOptions
      ? t("chat.options.label")
      : isThinking
        ? ""
        : typing
          ? t("chat.mini.skipHint")
          : canAdvance
            ? `${t("chat.mini.nextHint")} ▾`
            : "";

  const bubbleBodyText =
    notificationVisible && notificationText?.trim()
      ? notificationText.trim()
      : isThinking && !trimmedDialog
        ? busyText?.trim() || t("chat.mini.thinking")
        : dialogVisible && trimmedDialog
          ? trimmedDialog
          : reactionText || busyText?.trim() || t("chat.mini.thinking");

  return (
    <section
      aria-label={t("chat.mini.enter")}
      className="mini-avatar-stage"
      data-dock-side={effectiveDockSide}
      data-drag-active={dragActive ? "true" : "false"}
      data-standalone-desktop={standaloneDesktopWindow ? "true" : "false"}
    >
      <div className="mini-avatar-stage__anchor" style={anchorStyle}>
        <div
          className="mini-avatar__hub"
          data-chat-stage-hitbox={controlsVisible ? "true" : undefined}
          data-controls-visible={controlsVisible ? "true" : "false"}
          onBlurCapture={handleHubBlur}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onFocusCapture={handleHubFocus}
          onPointerEnter={handleHubPointerEnter}
          onPointerLeave={handleHubPointerLeave}
          ref={plusRootRef}
        >
          <div aria-hidden className="mini-avatar__ring" data-state={ringState} />

          <button
            aria-label={speakerLabel ? `${speakerLabel} · ${t("chat.mini.avatarHint")}` : t("chat.mini.avatarHint")}
            className="mini-avatar__core"
            data-chat-stage-hitbox="true"
            onClick={handleAvatarClick}
            onDoubleClick={handleAvatarDoubleClick}
            onPointerCancel={finishAvatarPointer}
            onPointerDown={handleAvatarPointerDown}
            onPointerMove={handleAvatarPointerMove}
            onPointerUp={finishAvatarPointer}
            title={t("chat.mini.avatarHint")}
            type="button"
          >
            {canRenderVisualAsset && activeSprite ? (
              <div className="mini-avatar__visual">
                <CharacterVisual
                  active
                  asset={{
                    avatarType: activeSprite.avatarType ?? STATIC_AVATAR_TYPE,
                    id: activeSprite.id,
                    label: activeSprite.label,
                    modelUrl: activeSprite.modelUrl ? stageAssetUrl(activeSprite.modelUrl) : "",
                    mouthSync: activeSprite.mouthSync ? stageAssetUrl(activeSprite.mouthSync) : undefined,
                    transitions: activeSprite.transitions?.map((edge) => ({
                      ...edge,
                      fromUrl: stageAssetUrl(edge.fromUrl),
                      url: stageAssetUrl(edge.url),
                    })),
                    url: activeSprite.path ? stageAssetUrl(activeSprite.path) : "",
                  }}
                  attention={isSpeaking ? "responding" : isThinking ? "thinking" : "idle"}
                  className="mini-avatar__visual-surface"
                  framing={activeFraming}
                  hitbox={false}
                  key={activeCharacterKey}
                  mode={activeSprite.applyMode ?? "play"}
                  onImageError={(event) => {
                    hideBrokenStageAsset(event);
                    setFailedSpriteAssetKey(activeSpriteAssetKey);
                  }}
                  onMouseDown={() => {}}
                  stateSequence={activeSprite.stateSequence}
                  voiceCharacterName={activeVoiceCharacterName}
                />
              </div>
            ) : (
              <span aria-hidden className="mini-avatar__fallback">
                {speakerInitial ? (
                  <span className="mini-avatar__initial">{speakerInitial}</span>
                ) : (
                  <UserRound className="mini-avatar__fallback-icon" />
                )}
              </span>
            )}
          </button>

          {asrEnabled || asrRunning || asrLoading ? (
            <span
              aria-label={t("chat.mini.micActive")}
              className="mini-avatar__mic-badge"
              data-listening={asrRunning ? "true" : "false"}
              role="status"
              title={t("chat.mini.micActive")}
            >
              <Mic aria-hidden className="mini-avatar__mic-badge-icon" />
            </span>
          ) : null}

          <div
            aria-label={t("chat.mini.controlsLabel")}
            className="mini-avatar__controls"
            data-visible={controlsVisible ? "true" : "false"}
            role="toolbar"
          >
            <IconButton
              className="mini-avatar__satellite mini-avatar__satellite--exit"
              label={t("chat.mini.exit")}
              onClick={onExitMiniMode}
              tabIndex={controlsVisible ? 0 : -1}
            >
              <Maximize2 aria-hidden className="icon-button__icon" />
            </IconButton>

            <IconButton
              aria-busy={asrLoading}
              aria-pressed={asrEnabled}
              className={classNames(
                "mini-avatar__satellite mini-avatar__satellite--voice",
                asrEnabled && "mini-avatar__satellite--active",
              )}
              data-active={asrEnabled ? "true" : "false"}
              disabled={locked || (inputDisabled && !asrEnabled)}
              label={asrLabel}
              onClick={toggleAsr}
              tabIndex={controlsVisible ? 0 : -1}
            >
              {asrIcon}
            </IconButton>

            <IconButton
              aria-expanded={inputPinned}
              aria-pressed={inputPinned}
              className={classNames(
                "mini-avatar__satellite mini-avatar__satellite--chat",
                inputPinned && "mini-avatar__satellite--active",
              )}
              data-active={inputPinned ? "true" : "false"}
              disabled={locked}
              label={t(inputPinned ? "chat.mini.collapseInput" : "chat.mini.toggleInput")}
              onClick={handleToggleInputPinned}
              onPointerEnter={() => setHoverBubblePreview(true)}
              tabIndex={controlsVisible ? 0 : -1}
            >
              <MessageSquare aria-hidden className="icon-button__icon" />
            </IconButton>

            <IconButton
              aria-expanded={plusMenuOpen}
              className={classNames(
                "mini-avatar__satellite mini-avatar__satellite--plus",
                plusMenuOpen && "mini-avatar__satellite--active",
              )}
              data-active={plusMenuOpen ? "true" : "false"}
              disabled={locked}
              label={t("chat.input.moreActions")}
              onClick={() => setPlusMenuOpen((current) => !current)}
              tabIndex={controlsVisible ? 0 : -1}
            >
              <Plus aria-hidden className="icon-button__icon" />
            </IconButton>
          </div>

          {plusMenuOpen ? (
            <div
              aria-label={t("chat.input.moreActions")}
              className="mini-avatar__plus-menu"
              data-chat-stage-hitbox="true"
              role="group"
            >
              <button
                className="mini-avatar__plus-item"
                disabled={inputDisabled}
                onClick={() => {
                  setPlusMenuOpen(false);
                  setInputPinned(true);
                  onPickAttachments("image");
                  focusInputSoon();
                }}
                type="button"
              >
                <ImagePlus aria-hidden className="mini-avatar__plus-icon" />
                <span>{t("chat.input.attachImage")}</span>
              </button>
              <button
                className="mini-avatar__plus-item"
                disabled={inputDisabled}
                onClick={() => {
                  setPlusMenuOpen(false);
                  setInputPinned(true);
                  onPickAttachments("file");
                  focusInputSoon();
                }}
                type="button"
              >
                <FileText aria-hidden className="mini-avatar__plus-icon" />
                <span>{t("chat.input.attachFile")}</span>
              </button>
              {onToggleScreenShare ? (
                <button
                  className="mini-avatar__plus-item"
                  disabled={screenShareStarting}
                  onClick={() => {
                    setPlusMenuOpen(false);
                    onToggleScreenShare();
                  }}
                  type="button"
                >
                  {screenSharing ? (
                    <MonitorOff aria-hidden className="mini-avatar__plus-icon" />
                  ) : (
                    <MonitorUp aria-hidden className="mini-avatar__plus-icon" />
                  )}
                  <span className="mini-avatar__plus-item-label">
                    {t(screenSharing ? "chat.toolbar.stopShareScreen" : "chat.toolbar.shareScreen")}
                  </span>
                </button>
              ) : null}
              {onAutoPlayChange ? (
                <button
                  aria-checked={autoPlay}
                  className={classNames("mini-avatar__plus-item", autoPlay && "mini-avatar__plus-item--active")}
                  onClick={() => {
                    setPlusMenuOpen(false);
                    onAutoPlayChange(!autoPlay);
                  }}
                  role="menuitemcheckbox"
                  type="button"
                >
                  <Play aria-hidden className="mini-avatar__plus-icon" />
                  <span className="mini-avatar__plus-item-label">{t("chat.toolbar.autoPlay")}</span>
                  {autoPlay ? <Check aria-hidden className="mini-avatar__plus-check" /> : null}
                </button>
              ) : null}
              {onLongPressTalkChange ? (
                <button
                  aria-checked={longPressTalk}
                  className={classNames("mini-avatar__plus-item", longPressTalk && "mini-avatar__plus-item--active")}
                  onClick={() => {
                    setPlusMenuOpen(false);
                    onLongPressTalkChange(!longPressTalk);
                  }}
                  role="menuitemcheckbox"
                  type="button"
                >
                  <Keyboard aria-hidden className="mini-avatar__plus-icon" />
                  <span className="mini-avatar__plus-item-label">{t("chat.config.longPressTalk")}</span>
                  {longPressTalk ? <Check aria-hidden className="mini-avatar__plus-check" /> : null}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        <aside
          aria-hidden={!bubbleVisible}
          aria-live="polite"
          className="mini-avatar__bubble"
          data-chat-stage-hitbox={bubbleVisible ? "true" : undefined}
          data-visible={bubbleVisible ? "true" : "false"}
          onClick={handleBubbleClick}
        >
          {speakerLabel || bubbleHint || (!isThinking && !toolConfirmation && !hasInteractiveOptions) ? (
            <div className="mini-avatar__bubble-header">
              {speakerLabel ? <span className="mini-avatar__bubble-speaker">{speakerLabel}</span> : <span />}
              <span className="mini-avatar__bubble-meta">
                {bubbleHint ? <span className="mini-avatar__bubble-hint">{bubbleHint}</span> : null}
                {!toolConfirmation && !hasInteractiveOptions && !isThinking && !typing && !canAdvance ? (
                  <button
                    aria-label={t("chat.mini.dismissBubble")}
                    className="mini-avatar__bubble-dismiss"
                    onClick={(event) => {
                      event.stopPropagation();
                      setIdleDismissed(true);
                      setHoverBubblePreview(false);
                    }}
                    title={t("chat.mini.dismissBubble")}
                    type="button"
                  >
                    <X aria-hidden className="mini-avatar__bubble-dismiss-icon" />
                  </button>
                ) : null}
              </span>
            </div>
          ) : null}

          <div className="mini-avatar__bubble-body">{bubbleBodyText}</div>

          {toolConfirmation ? (
            <div aria-label={t("chat.toolConfirmation.label")} className="mini-avatar__bubble-options" role="list">
              <button
                className="mini-avatar__option-button"
                onClick={() => onResolveToolConfirmation("confirm")}
                type="button"
              >
                {t("chat.toolConfirmation.confirm", { tool: toolConfirmation.toolName })}
              </button>
              <button
                className="mini-avatar__option-button mini-avatar__option-button--muted"
                onClick={() => onResolveToolConfirmation("cancel")}
                type="button"
              >
                {t("common.cancel")}
              </button>
            </div>
          ) : hasInteractiveOptions ? (
            <div aria-label={t("chat.options.label")} className="mini-avatar__bubble-options" role="list">
              {options.map((option) => {
                const label = typeof option === "string" ? option : option.label;
                const disabled = locked || (typeof option !== "string" && !option.enabled);
                const key = typeof option === "string" ? option : `${option.expectedRevision}:${option.id}`;
                return (
                  <button
                    className="mini-avatar__option-button"
                    disabled={disabled}
                    key={key}
                    onClick={() => onSelectOption(option)}
                    type="button"
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          ) : null}
        </aside>

        {inputVisible ? (
          <div
            className="mini-avatar__input-bar"
            data-chat-stage-hitbox="true"
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            {attachments.length ? (
              <div aria-label={t("chat.input.attachments")} className="mini-avatar__attachments">
                {attachments.map((attachment) => (
                  <button
                    aria-label={t("chat.input.removeAttachment", { name: attachment.name })}
                    className="mini-avatar__attachment-chip"
                    disabled={inputDisabled}
                    key={`${attachment.kind}:${attachment.path}`}
                    onClick={() => onRemoveAttachment(attachment)}
                    title={attachment.name}
                    type="button"
                  >
                    <span className="mini-avatar__attachment-name">{attachment.name}</span>
                    <X aria-hidden className="mini-avatar__attachment-remove" />
                  </button>
                ))}
              </div>
            ) : null}
            <div className="mini-avatar__input-row">
              <TextInput
                autoComplete="off"
                className="mini-avatar__input"
                disabled={inputDisabled || locked}
                onChange={(event) => handleInputChange(event.target.value)}
                onCompositionEnd={(event) => reportInputActivity(event.currentTarget.value, false)}
                onCompositionStart={(event) => reportInputActivity(event.currentTarget.value, true)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && !event.nativeEvent.isComposing && !(longPressTalk && asrRunning)) {
                    event.preventDefault();
                    setInputPinned(false);
                    return;
                  }
                  if (event.key === "ArrowUp" && !event.nativeEvent.isComposing && recallPreviousMessage()) {
                    event.preventDefault();
                    return;
                  }
                  if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    void submitKeepingExpanded(event.ctrlKey);
                  }
                }}
                placeholder={t("chat.input.placeholder")}
                ref={inputRef}
                value={inputValue}
              />
              <IconButton
                className="mini-avatar__send-button"
                disabled={!canSubmit}
                label={t("chat.input.send")}
                onClick={() => void submitKeepingExpanded(false)}
              >
                <Send aria-hidden className="icon-button__icon" />
              </IconButton>
              {inputPinned ? (
                <IconButton
                  className="mini-avatar__close-input"
                  label={t("chat.mini.collapseInput")}
                  onClick={() => setInputPinned(false)}
                >
                  <X aria-hidden className="icon-button__icon" />
                </IconButton>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
