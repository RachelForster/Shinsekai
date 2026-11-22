import "./ImageAssetGallery.css";
import { useEffect, useState } from "react";
import type { UIEvent } from "react";
import { Image as ImageIcon } from "lucide-react";
import { VisualMedia } from "./VisualMedia";

export interface ImageAssetGalleryItem {
  badge?: string;
  badgeTone?: "default" | "muted";
  cornerLabel?: string;
  globalIndex?: number;
  id: string;
  imageSrc?: string;
  videoSrc?: string;
  meta?: string;
  secondaryBadge?: string;
  title: string;
}

export function ImageAssetCornerLabel({ children }: { children: string }) {
  return <span className="image-asset-corner-label">{children}</span>;
}

interface ImageAssetGalleryProps {
  checkedIndices?: ReadonlySet<number>;
  checkLabel?: (item: ImageAssetGalleryItem, globalIndex: number) => string;
  imageDecoding?: "async" | "auto" | "sync";
  imageLoading?: "eager" | "lazy";
  items: ImageAssetGalleryItem[];
  nearEndThreshold?: number;
  onNearEnd?: () => void;
  onSelect: (index: number) => void;
  onToggleCheck?: (globalIndex: number) => void;
  selectedIndex: number;
}

interface ImageAssetThumbProps {
  alt?: string;
  decoding?: "async" | "auto" | "sync";
  loading?: "eager" | "lazy";
  src?: string;
}

function imageThumbStateForSource(src?: string): "empty" | "loaded" | "loading" {
  if (!src) {
    return "empty";
  }
  return src.startsWith("data:image/") ? "loaded" : "loading";
}

export function ImageAssetThumb({ alt = "", decoding = "async", loading = "lazy", src }: ImageAssetThumbProps) {
  const [state, setState] = useState<"empty" | "error" | "loaded" | "loading">(() => imageThumbStateForSource(src));

  useEffect(() => {
    setState(imageThumbStateForSource(src));
  }, [src]);

  const showPlaceholder = state !== "loaded";

  return (
    <span className="image-asset-card__media" data-state={state}>
      {src ? (
        <img
          alt={alt}
          decoding={decoding}
          loading={loading}
          onError={() => setState("error")}
          onLoad={(event) => {
            const image = event.currentTarget;
            setState(image.naturalWidth > 0 ? "loaded" : "error");
          }}
          src={src}
        />
      ) : null}
      {showPlaceholder ? (
        <span aria-hidden className="image-asset-card__placeholder">
          <ImageIcon className="image-asset-card__fallback" />
        </span>
      ) : null}
    </span>
  );
}

function VideoAssetThumb({ src }: { src: string }) {
  const [state, setState] = useState("loading");
  return (
    <span className="image-asset-card__media" data-state={state}>
      <VisualMedia
        alt=""
        autoPlay={false}
        loading="lazy"
        onError={() => setState("error")}
        onLoad={() => setState("loaded")}
        src={src}
      />
      {state !== "loaded" ? (
        <span aria-hidden className="image-asset-card__placeholder">
          <ImageIcon className="image-asset-card__fallback" />
        </span>
      ) : null}
    </span>
  );
}

export function ImageAssetGallery({
  checkedIndices,
  checkLabel,
  imageDecoding = "async",
  imageLoading = "lazy",
  items,
  nearEndThreshold = 160,
  onNearEnd,
  onSelect,
  onToggleCheck,
  selectedIndex,
}: ImageAssetGalleryProps) {
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    if (!onNearEnd) {
      return;
    }
    const element = event.currentTarget;
    if (element.scrollHeight - element.scrollTop - element.clientHeight <= nearEndThreshold) {
      onNearEnd();
    }
  };

  return (
    <div className="image-asset-gallery" onScroll={handleScroll}>
      {items.map((item, index) => {
        const itemIndex = item.globalIndex ?? index;
        const card = (
          <button
            aria-selected={itemIndex === selectedIndex}
            className="image-asset-card"
            key={onToggleCheck ? undefined : item.id}
            onClick={() => onSelect(itemIndex)}
            title={item.title}
            type="button"
          >
            {item.videoSrc ? (
              <VideoAssetThumb key={item.videoSrc} src={item.videoSrc} />
            ) : (
              <ImageAssetThumb decoding={imageDecoding} loading={imageLoading} src={item.imageSrc} />
            )}
            {item.cornerLabel ? <ImageAssetCornerLabel>{item.cornerLabel}</ImageAssetCornerLabel> : null}
            <span className="image-asset-card__body">
              <span className="image-asset-card__title">
                <span>{itemIndex + 1}</span>
                <strong>{item.title}</strong>
              </span>
              {item.meta ? <span className="image-asset-card__meta">{item.meta}</span> : null}
            </span>
            {item.secondaryBadge ? (
              <span className="image-asset-card__badges">
                {item.badge ? (
                  <span className={`image-asset-card__badge image-asset-card__badge--${item.badgeTone ?? "default"}`}>
                    {item.badge}
                  </span>
                ) : null}
                <span className="image-asset-card__badge image-asset-card__badge--group">{item.secondaryBadge}</span>
              </span>
            ) : item.badge ? (
              <span className={`image-asset-card__badge image-asset-card__badge--${item.badgeTone ?? "default"}`}>
                {item.badge}
              </span>
            ) : null}
          </button>
        );

        if (!onToggleCheck) {
          return card;
        }
        const checked = Boolean(checkedIndices?.has(itemIndex));
        return (
          <div className="image-asset-card-cell" data-checked={checked ? "true" : "false"} key={item.id}>
            {card}
            <input
              aria-label={checkLabel ? checkLabel(item, itemIndex) : item.title}
              checked={checked}
              className="image-asset-card__checkbox"
              onChange={() => onToggleCheck(itemIndex)}
              type="checkbox"
            />
          </div>
        );
      })}
    </div>
  );
}
