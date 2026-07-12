import { createElement, type CSSProperties, type MouseEvent, type MouseEventHandler, type ReactNode } from "react";

import { startDesktopWindowResize, type DesktopResizeDirection } from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import { Button } from "../../../shared/ui";
import type { ChatStageSprite } from "../chatState";
import { classNames, hideBrokenStageAsset, layerClassName, stageAssetUrl } from "../chatStageUtils";
import type { DialogHtmlNode, DialogHtmlStyleProperty } from "../dialogTypewriter";

function closestDialogInteractiveElement(target: EventTarget | null) {
  if (!(target instanceof Element)) {
    return null;
  }
  return target.closest("a, button, input, textarea, select, summary, [role='button'], [role='link']");
}

export function BackgroundLayer({
  hidden,
  path,
  transparent,
}: {
  hidden: boolean;
  path?: string;
  transparent: boolean;
}) {
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
  const spriteName = (sprite: ChatStageSprite) => (sprite.characterName ?? sprite.label ?? "").trim();
  const hasSpeakingSprite = activeSpeaker.length > 0 && sprites.some((sprite) => spriteName(sprite) === activeSpeaker);
  return (
    <div
      aria-hidden={hidden}
      className={layerClassName("sprite-layer", hidden)}
      data-count={sprites.length}
      hidden={hidden}
    >
      {sprites.map((sprite, index) => {
        const speaking = hasSpeakingSprite && spriteName(sprite) === activeSpeaker;
        return (
          <figure
            className="sprite-layer__figure"
            data-chat-stage-hitbox={onDragStart ? "true" : undefined}
            data-dim={hasSpeakingSprite && !speaking ? "true" : "false"}
            data-draggable={onDragStart ? "true" : "false"}
            data-slot={sprite.slot ?? index}
            data-speaking={speaking ? "true" : "false"}
            key={sprite.id}
            onMouseDown={onDragStart}
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
      {characterName ? <p className="dialog-layer__name">{characterName}</p> : null}
      {htmlNodes !== undefined ? (
        <div className="dialog-layer__body">
          <div className="dialog-layer__text" data-text-direction={textDirection} dir={renderedDirection}>
            <div className="dialog-layer__html">{renderDialogHtmlNodes(htmlNodes)}</div>
            {canAdvance && !typing ? <span aria-hidden className="dialog-layer__ctc" /> : null}
          </div>
        </div>
      ) : (
        <div className="dialog-layer__body">
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

export function NotificationLayer({ hidden, text }: { hidden: boolean; text?: string }) {
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
