import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEventHandler,
  type ReactNode,
  type SyntheticEvent,
  type WheelEventHandler,
} from "react";

import { stageAssetUrl } from "../../features/chat-stage/chatStageUtils";
import { isVideoMedia } from "../assets/visualMedia";
import type { Character, PortraitCrop } from "../platform/types";
import { VisualMedia, type VisualMediaElement } from "../ui/VisualMedia";
import "./Portrait.css";

export const defaultPortraitCrop: PortraitCrop = { x: 0.5, y: 0.2, zoom: 1 };

export function normalizePortraitCrop(crop?: PortraitCrop | null): PortraitCrop {
  return {
    x:
      typeof crop?.x === "number" && Number.isFinite(crop.x) ? Math.min(1, Math.max(0, crop.x)) : defaultPortraitCrop.x,
    y:
      typeof crop?.y === "number" && Number.isFinite(crop.y) ? Math.min(1, Math.max(0, crop.y)) : defaultPortraitCrop.y,
    zoom:
      typeof crop?.zoom === "number" && Number.isFinite(crop.zoom)
        ? Math.min(8, Math.max(1, crop.zoom))
        : defaultPortraitCrop.zoom,
  };
}

export function resolveSpritePortraitCrop(
  character?: Pick<Character, "portrait_crop" | "sprites"> | null,
  spriteIndex = 0,
): PortraitCrop {
  return normalizePortraitCrop(
    character?.sprites?.[spriteIndex]?.portrait_crop ?? character?.portrait_crop ?? defaultPortraitCrop,
  );
}

export function applyPortraitCrop(
  character: Character,
  spriteIndex: number,
  individual: boolean,
  crop: PortraitCrop,
): Character {
  const next = structuredClone(character);
  if (!next.sprites[spriteIndex]) return next;
  const normalized = normalizePortraitCrop(crop);
  if (individual) {
    next.sprites[spriteIndex].portrait_crop = normalized;
  } else {
    next.portrait_crop = normalized;
    next.sprites[spriteIndex].portrait_crop = null;
  }
  return next;
}

export function portraitGeometry(width: number, height: number, crop: PortraitCrop) {
  const normalized = normalizePortraitCrop(crop);
  const side = Math.min(width, height) / normalized.zoom;
  const left = Math.max(0, Math.min(width - side, normalized.x * width - side / 2));
  const top = Math.max(0, Math.min(height - side, normalized.y * height - side / 2));
  return { side, left, top };
}

export function portraitViewportGeometry(width: number, height: number, crop: PortraitCrop, containerAspect = 1) {
  const safeWidth = Math.max(1, width);
  const safeHeight = Math.max(1, height);
  const aspect = Number.isFinite(containerAspect) && containerAspect > 0 ? containerAspect : 1;
  if (Math.abs(aspect - 1) < 1e-4) {
    const { side, left, top } = portraitGeometry(safeWidth, safeHeight, crop);
    return { width: side, height: side, left, top };
  }
  const normalized = normalizePortraitCrop(crop);
  const side = Math.min(safeWidth, safeHeight) / normalized.zoom;
  let viewWidth = aspect >= 1 ? side * aspect : side;
  let viewHeight = aspect >= 1 ? side : side / aspect;
  const fitScale = Math.min(1, safeWidth / viewWidth, safeHeight / viewHeight);
  viewWidth *= fitScale;
  viewHeight *= fitScale;
  const left = Math.max(0, Math.min(safeWidth - viewWidth, normalized.x * safeWidth - viewWidth / 2));
  const top = Math.max(0, Math.min(safeHeight - viewHeight, normalized.y * safeHeight - viewHeight / 2));
  return { width: viewWidth, height: viewHeight, left, top };
}

export type PortraitShape = "square" | "circle" | "fill";

export interface PortraitMediaRenderProps {
  active: boolean;
  alt: string;
  loading?: "eager" | "lazy";
  onDimensions: (width: number, height: number) => void;
  onError?: (event: SyntheticEvent<VisualMediaElement, Event>) => void;
  src: string;
  style: CSSProperties;
}

export interface PortraitProps {
  path?: string;
  crop?: PortraitCrop | null;
  name: string;
  alt?: string;
  ariaHidden?: boolean;
  size?: CSSProperties["width"];
  shape?: PortraitShape;
  className?: string;
  active?: boolean;
  loading?: "eager" | "lazy";
  fallback?: ReactNode;
  children?: ReactNode;
  renderMedia?: (props: PortraitMediaRenderProps) => ReactNode;
  onPointerDown?: PointerEventHandler<HTMLDivElement>;
  onPointerMove?: PointerEventHandler<HTMLDivElement>;
  onWheel?: WheelEventHandler<HTMLDivElement>;
  onImageSize?: (width: number, height: number) => void;
  onError?: (event: SyntheticEvent<VisualMediaElement, Event>) => void;
}

export function Portrait({
  path,
  crop = defaultPortraitCrop,
  name,
  alt,
  ariaHidden,
  size = "100%",
  shape = "square",
  className,
  active = true,
  loading,
  fallback,
  children,
  renderMedia,
  onPointerDown,
  onPointerMove,
  onWheel,
  onImageSize,
  onError,
}: PortraitProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [image, setImage] = useState({ path: "", width: 1, height: 1 });
  const [failedPath, setFailedPath] = useState<string | null>(null);
  const [containerAspect, setContainerAspect] = useState(1);

  useEffect(() => {
    if (shape !== "fill") {
      setContainerAspect(1);
      return;
    }
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const updateAspect = () => {
      if (element.clientWidth > 0 && element.clientHeight > 0) {
        setContainerAspect(element.clientWidth / element.clientHeight);
      }
    };
    updateAspect();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(updateAspect);
    observer.observe(element);
    return () => observer.disconnect();
  }, [shape]);

  const normalizedCrop = normalizePortraitCrop(crop);
  const resolvedSrc = path ? stageAssetUrl(path) : "";
  const hasMedia = Boolean(path && resolvedSrc && failedPath !== path);
  const hasMeasuredDimensions = Boolean(path && image.path === path && image.width > 0 && image.height > 0);
  const measuredWidth = hasMeasuredDimensions ? image.width : 1;
  const measuredHeight = hasMeasuredDimensions ? image.height : 1;
  const viewport = portraitViewportGeometry(
    measuredWidth,
    measuredHeight,
    normalizedCrop,
    shape === "fill" ? containerAspect : 1,
  );
  const initial = Array.from(name.trim())[0] ?? "";
  const resolvedAlt = alt ?? name;
  const orientation = hasMeasuredDimensions && image.width > image.height ? "landscape" : "portrait";

  const mediaStyle: CSSProperties = {
    position: "absolute",
    maxWidth: "none",
    maxHeight: "none",
    width: `${(measuredWidth / viewport.width) * 100}%`,
    height: `${(measuredHeight / viewport.height) * 100}%`,
    left: `${(-viewport.left / viewport.width) * 100}%`,
    top: `${(-viewport.top / viewport.height) * 100}%`,
    visibility: hasMeasuredDimensions ? "visible" : "hidden",
    pointerEvents: "none",
  };

  const handleDimensions = (width: number, height: number) => {
    if (!path || width <= 0 || height <= 0) {
      return;
    }
    setFailedPath((current) => (current === path ? null : current));
    setImage({ path, width, height });
    onImageSize?.(width, height);
  };

  const interceptError = !isVideoMedia(resolvedSrc) || Boolean(onError);
  const handleError = interceptError
    ? (event: SyntheticEvent<VisualMediaElement, Event>) => {
        if (path) {
          setFailedPath(path);
        }
        onError?.(event);
      }
    : undefined;

  const classes = ["portrait", `portrait--${shape}`, className].filter(Boolean).join(" ");
  const containerStyle: CSSProperties = {
    ...(shape === "fill" ? undefined : { width: size }),
    ...(onPointerDown ? { touchAction: "none" } : undefined),
  };

  const mediaProps: PortraitMediaRenderProps = {
    active,
    alt: resolvedAlt,
    loading,
    onDimensions: handleDimensions,
    onError: handleError,
    src: resolvedSrc,
    style: mediaStyle,
  };

  return (
    <div
      aria-hidden={ariaHidden}
      className={classes}
      data-measured={hasMeasuredDimensions ? "true" : "false"}
      data-orientation={orientation}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onWheel={onWheel}
      ref={containerRef}
      style={containerStyle}
    >
      {hasMedia ? (
        renderMedia ? (
          renderMedia(mediaProps)
        ) : (
          <VisualMedia
            active={mediaProps.active}
            alt={mediaProps.alt}
            loading={mediaProps.loading}
            onDimensions={mediaProps.onDimensions}
            onError={mediaProps.onError}
            src={mediaProps.src}
            style={mediaProps.style}
          />
        )
      ) : (
        (fallback ?? (
          <span aria-hidden className="portrait__fallback">
            {initial}
          </span>
        ))
      )}
      {children}
    </div>
  );
}
