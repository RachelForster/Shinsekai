import "./ImageAssetGallery.css";
import { useEffect, useState } from "react";
import type { UIEvent } from "react";
import { Image as ImageIcon } from "lucide-react";

export interface ImageAssetGalleryItem {
  badge?: string;
  badgeTone?: "default" | "muted";
  id: string;
  imageSrc?: string;
  meta?: string;
  title: string;
}

interface ImageAssetGalleryProps {
  imageDecoding?: "async" | "auto" | "sync";
  imageLoading?: "eager" | "lazy";
  items: ImageAssetGalleryItem[];
  nearEndThreshold?: number;
  onNearEnd?: () => void;
  onSelect: (index: number) => void;
  selectedIndex: number;
}

interface ImageAssetThumbProps {
  decoding: "async" | "auto" | "sync";
  loading: "eager" | "lazy";
  src?: string;
}

function imageThumbStateForSource(src?: string): "empty" | "loaded" | "loading" {
  if (!src) {
    return "empty";
  }
  return src.startsWith("data:image/") ? "loaded" : "loading";
}

function ImageAssetThumb({ decoding, loading, src }: ImageAssetThumbProps) {
  const [state, setState] = useState<"empty" | "error" | "loaded" | "loading">(() => imageThumbStateForSource(src));

  useEffect(() => {
    setState(imageThumbStateForSource(src));
  }, [src]);

  const showPlaceholder = state !== "loaded";

  return (
    <span className="image-asset-card__media" data-state={state}>
      {src ? (
        <img
          alt=""
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

export function ImageAssetGallery({
  imageDecoding = "async",
  imageLoading = "lazy",
  items,
  nearEndThreshold = 160,
  onNearEnd,
  onSelect,
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
      {items.map((item, index) => (
        <button
          aria-selected={index === selectedIndex}
          className="image-asset-card"
          key={item.id}
          onClick={() => onSelect(index)}
          title={item.title}
          type="button"
        >
          <ImageAssetThumb decoding={imageDecoding} loading={imageLoading} src={item.imageSrc} />
          <span className="image-asset-card__body">
            <span className="image-asset-card__title">
              <span>{index + 1}</span>
              <strong>{item.title}</strong>
            </span>
            {item.meta ? <span className="image-asset-card__meta">{item.meta}</span> : null}
          </span>
          {item.badge ? (
            <span className={`image-asset-card__badge image-asset-card__badge--${item.badgeTone ?? "default"}`}>
              {item.badge}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}
