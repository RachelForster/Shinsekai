import {
  createElement,
  useEffect,
  useRef,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type MouseEventHandler,
  type ReactNode,
} from "react";
import { Clock, Coins, Gauge, Heart, Shield, Sparkles, Star, Target, Zap, type LucideIcon } from "lucide-react";

import { startDesktopWindowResize, type DesktopResizeDirection } from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import type { ChatStat } from "../../../shared/platform/types";
import { Button, ThemeFrame } from "../../../shared/ui";
import type { ChatStageSprite } from "../chatState";
import { classNames, hideBrokenStageAsset, layerClassName, stageAssetUrl } from "../chatStageUtils";
import type { DialogHtmlNode, DialogHtmlStyleProperty } from "../dialogTypewriter";
import { chatStageSpriteAxisCenter, chatStageSpriteCharacterName } from "../state/sprites";

function closestDialogInteractiveElement(target: EventTarget | null) {
  if (!(target instanceof Element)) {
    return null;
  }
  return target.closest("a, button, input, textarea, select, summary, [role='button'], [role='link']");
}

export function BackgroundLayer({
  hidden,
  onDragStart,
  path,
  transparent,
}: {
  hidden: boolean;
  onDragStart?: MouseEventHandler<HTMLElement>;
  path?: string;
  transparent: boolean;
}) {
  const src = stageAssetUrl(path);
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__background", hidden)}
      data-chat-stage-hitbox={onDragStart ? "true" : undefined}
      data-draggable={onDragStart ? "true" : "false"}
      data-transparent={transparent ? "true" : "false"}
      hidden={hidden}
      onMouseDown={onDragStart}
    >
      {transparent ? null : <div aria-hidden className="chat-stage__fallback" />}
      {src ? <img alt="" onError={hideBrokenStageAsset} src={src} /> : null}
    </div>
  );
}

export function BgmLayer({ path, volume = 1 }: { path?: string; volume?: number }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const src = stageAssetUrl(path);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.volume = Math.min(1, Math.max(0, volume));
    }
  }, [volume, src]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !src) {
      return;
    }

    let disposed = false;
    const play = () => {
      if (disposed) {
        return;
      }
      const request = audio.play();
      if (request) {
        void request.catch(() => undefined);
      }
    };
    const request = audio.play();
    if (request) {
      void request.catch(() => {
        if (!disposed) {
          document.addEventListener("pointerdown", play, { once: true });
        }
      });
    }

    return () => {
      disposed = true;
      document.removeEventListener("pointerdown", play);
      audio.pause();
    };
  }, [src]);

  return src ? <audio aria-hidden data-chat-stage-bgm loop preload="auto" ref={audioRef} src={src} /> : null;
}

export function CgLayer({ hidden, path }: { hidden: boolean; path?: string }) {
  const src = stageAssetUrl(path);
  return (
    <div aria-hidden={hidden} className={layerClassName("chat-stage__cg", hidden)} hidden={hidden}>
      {src ? <img alt="" onError={hideBrokenStageAsset} src={src} /> : null}
    </div>
  );
}

export function SpriteLayer({
  hidden,
  onDragStart,
  runtimeScaleForSprite,
  speaker,
  sprites,
}: {
  hidden: boolean;
  onDragStart?: MouseEventHandler<HTMLElement>;
  runtimeScaleForSprite: (sprite: ChatStageSprite, index: number) => number;
  speaker?: string;
  sprites: ChatStageSprite[];
}) {
  const activeSpeaker = speaker?.trim() ?? "";
  const hasSpeakingSprite =
    activeSpeaker.length > 0 && sprites.some((sprite) => chatStageSpriteCharacterName(sprite) === activeSpeaker);
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("sprite-layer", hidden)}
      data-count={sprites.length}
      hidden={hidden}
    >
      {sprites.map((sprite, index) => {
        const speaking = hasSpeakingSprite && chatStageSpriteCharacterName(sprite) === activeSpeaker;
        const axisCenter = chatStageSpriteAxisCenter(sprites, sprite, index);
        return (
          <figure
            className="sprite-layer__figure"
            data-axis-center={String(axisCenter)}
            data-dim={hasSpeakingSprite && !speaking ? "true" : "false"}
            data-draggable={onDragStart ? "true" : "false"}
            data-slot={sprite.slot ?? index}
            data-speaking={speaking ? "true" : "false"}
            key={sprite.id}
            style={
              {
                "--sprite-axis-center": `${axisCenter}%`,
                "--sprite-layer-order": index + 1,
                "--sprite-offset-x": `${sprite.x ?? 0}px`,
                "--sprite-offset-y": `${sprite.y ?? 0}px`,
                "--sprite-scale": (sprite.scale ?? 1) * runtimeScaleForSprite(sprite, index),
              } as CSSProperties
            }
          >
            <img
              alt={sprite.label}
              className="sprite-layer__image"
              data-chat-stage-hitbox={onDragStart ? "true" : undefined}
              key={sprite.path}
              onError={hideBrokenStageAsset}
              onMouseDown={onDragStart}
              src={stageAssetUrl(sprite.path)}
            />
          </figure>
        );
      })}
    </div>
  );
}

export function DialogLayer({
  canAdvance,
  characterName,
  hidden,
  htmlNodes,
  onAdvance,
  onSkip,
  text,
  textDirection = "ltr",
  toolbar,
  typing,
}: {
  canAdvance: boolean;
  characterName?: string;
  hidden: boolean;
  htmlNodes?: DialogHtmlNode[];
  onAdvance?: () => void;
  onSkip?: () => void;
  text: string;
  textDirection?: "ltr" | "rtl";
  toolbar?: ReactNode;
  typing: boolean;
}) {
  const handleDialogClick = (event: MouseEvent<HTMLElement>) => {
    if (closestDialogInteractiveElement(event.target)) {
      return;
    }
    if (typing) {
      onSkip?.();
      return;
    }
    if (canAdvance) {
      onAdvance?.();
    }
  };
  const renderedDirection = textDirection === "rtl" ? "ltr" : textDirection;

  const bodyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // Keep the newest content in view: follow the typewriter reveal and the
    // growing batched-input preview by pinning the dialogue box to the bottom.
    const body = bodyRef.current;
    if (body) {
      body.scrollTop = body.scrollHeight;
    }
  }, [htmlNodes, text]);

  return (
    <section
      aria-hidden={hidden}
      aria-live="polite"
      className={layerClassName("dialog-layer", hidden)}
      data-chat-stage-hitbox="true"
      data-has-toolbar={toolbar ? "true" : "false"}
      data-typing={typing ? "true" : "false"}
      hidden={hidden}
      onClick={handleDialogClick}
    >
      <ThemeFrame prefix="chat-dialog" />
      {characterName ? (
        <p className="dialog-layer__name">
          <ThemeFrame prefix="chat-name" />
          <span className="dialog-layer__name-content">{characterName}</span>
        </p>
      ) : null}
      {htmlNodes !== undefined ? (
        <div className="dialog-layer__body" ref={bodyRef}>
          <div className="dialog-layer__text" data-text-direction={textDirection} dir={renderedDirection}>
            <div className="dialog-layer__html">{renderDialogHtmlNodes(htmlNodes)}</div>
            {canAdvance && !typing ? <span aria-hidden className="dialog-layer__ctc" /> : null}
          </div>
        </div>
      ) : (
        <div className="dialog-layer__body" ref={bodyRef}>
          <div className="dialog-layer__text" data-text-direction={textDirection} dir={renderedDirection}>
            {text}
            {canAdvance && !typing ? <span aria-hidden className="dialog-layer__ctc" /> : null}
          </div>
        </div>
      )}
      <PluginSlot slot="chat-output" />
      {toolbar ? <div className="dialog-layer__toolbar">{toolbar}</div> : null}
    </section>
  );
}

const dialogStylePropMap: Record<DialogHtmlStyleProperty, keyof CSSProperties> = {
  color: "color",
  "font-style": "fontStyle",
  "font-weight": "fontWeight",
  "letter-spacing": "letterSpacing",
  "line-height": "lineHeight",
  "text-decoration": "textDecoration",
};

function dialogNodeStyle(style?: Partial<Record<DialogHtmlStyleProperty, string>>) {
  if (!style) {
    return undefined;
  }
  const out: CSSProperties = {};
  Object.entries(style).forEach(([key, value]) => {
    const prop = dialogStylePropMap[key as DialogHtmlStyleProperty];
    if (prop && value) {
      (out as Record<string, string>)[prop] = value;
    }
  });
  return Object.keys(out).length ? out : undefined;
}

function renderDialogHtmlNode(node: DialogHtmlNode, key: string): ReactNode {
  if (node.kind === "text") {
    return node.text;
  }

  const props: {
    className?: string;
    href?: string;
    key: string;
    rel?: string;
    style?: CSSProperties;
    target?: string;
  } = { key };
  if (node.attrs?.className) {
    props.className = node.attrs.className;
  }
  if (node.attrs?.style) {
    props.style = dialogNodeStyle(node.attrs.style);
  }
  if (node.tag === "a" && node.attrs?.href) {
    props.href = node.attrs.href;
    props.rel = node.attrs.rel;
    props.target = node.attrs.target;
  }
  if (node.tag === "br") {
    return createElement("br", props);
  }
  return createElement(
    node.tag,
    props,
    node.children.map((child, index) => renderDialogHtmlNode(child, `${key}-${index}`)),
  );
}

function renderDialogHtmlNodes(nodes: DialogHtmlNode[]) {
  return nodes.map((node, index) => renderDialogHtmlNode(node, `dialog-html-${index}`));
}

export function OptionsLayer({
  hidden,
  onSelect,
  options,
}: {
  hidden: boolean;
  onSelect: (option: string) => void;
  options: string[];
}) {
  const { t } = useI18n();
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
      <div aria-label={t("chat.options.label")} className="options-layer__scroll" role="list">
        {options.map((option, index) => (
          <div className="options-layer__item" key={option} role="listitem">
            <ThemeFrame prefix="chat-option" />
            <Button
              autoFocus={index === 0}
              className="options-layer__button"
              onClick={() => onSelect(option)}
              onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => {
                if (event.key !== "Enter" || event.nativeEvent.isComposing) {
                  return;
                }
                event.preventDefault();
                event.stopPropagation();
                onSelect(option);
              }}
            >
              {option}
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BusyLayer({ hidden, text }: { hidden: boolean; text?: string }) {
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

export function NotificationLayer({
  hidden,
  spritesVisible,
  text,
}: {
  hidden: boolean;
  spritesVisible: boolean;
  text?: string;
}) {
  if (hidden || !text) {
    return null;
  }
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("chat-stage__notification", hidden)}
      data-chat-stage-hitbox="true"
      data-sprites-visible={spritesVisible ? "true" : "false"}
      hidden={hidden}
      role="status"
    >
      {text}
    </div>
  );
}

const statIcons: Record<ChatStat["icon"], LucideIcon> = {
  clock: Clock,
  coins: Coins,
  gauge: Gauge,
  heart: Heart,
  shield: Shield,
  sparkles: Sparkles,
  star: Star,
  target: Target,
  zap: Zap,
};

function formatStatNumber(value: number) {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

export function StatLayer({ stats }: { stats: ChatStat[] }) {
  const { t } = useI18n();
  if (!stats.length) {
    return null;
  }
  return (
    <aside aria-label={t("chat.stats.label")} className="stat-layer" role="status">
      {stats.map((stat, index) => {
        const Icon = statIcons[stat.icon] ?? Gauge;
        const hasRange = typeof stat.max === "number" && Number.isFinite(stat.max) && stat.max > 0;
        const progressValue = hasRange ? Math.min(Math.max(stat.value, 0), stat.max as number) : undefined;
        return (
          <article className="stat-layer__item" data-icon={stat.icon} key={`${stat.label}-${index}`}>
            <span aria-hidden className="stat-layer__icon">
              <Icon />
            </span>
            <span className="stat-layer__label">{stat.label}</span>
            <output className="stat-layer__value">
              {formatStatNumber(stat.value)}
              {hasRange ? <span className="stat-layer__maximum"> / {formatStatNumber(stat.max as number)}</span> : null}
            </output>
            {hasRange ? (
              <progress aria-label={stat.label} className="stat-layer__progress" max={stat.max} value={progressValue} />
            ) : null}
          </article>
        );
      })}
    </aside>
  );
}

function tokenUsageSegments(text: string) {
  return text
    .split(/\n|\|/g)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

export function TokenUsageLayer({ hidden, text }: { hidden: boolean; text?: string }) {
  const { t } = useI18n();
  if (hidden || !text) {
    return null;
  }
  const segments = tokenUsageSegments(text);
  return (
    <section className="token-usage-layer" data-chat-stage-hitbox="true" role="status">
      <span className="token-usage-layer__title">{t("chat.toolbar.tokens")}</span>
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

export function StandaloneDesktopResizeHandles({ hidden }: { hidden: boolean }) {
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
