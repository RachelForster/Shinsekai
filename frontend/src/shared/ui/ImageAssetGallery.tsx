import "./ImageAssetGallery.css";
import { useEffect, useState } from "react";
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
  onSelect: (index: number) => void;
  selectedIndex: number;
}

interface ImageAssetThumbProps {
  decoding: "async" | "auto" | "sync";
  loading: "eager" | "lazy";
  src?: string;
}

function ImageAssetThumb({ decoding, loading, src }: ImageAssetThumbProps) {
  const [state, setState] = useState<"empty" | "error" | "loaded" | "loading">(src ? "loading" : "empty");

  useEffect(() => {
    setState(src ? "loading" : "empty");
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
            if (typeof image.decode !== "function") {
              setState(image.naturalWidth > 0 ? "loaded" : "error");
              return;
            }
            void image
              .decode()
              .then(() => setState("loaded"))
              .catch(() => setState(image.naturalWidth > 0 ? "loaded" : "error"));
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
  onSelect,
  selectedIndex,
}: ImageAssetGalleryProps) {
  return (
    <div className="image-asset-gallery">
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
