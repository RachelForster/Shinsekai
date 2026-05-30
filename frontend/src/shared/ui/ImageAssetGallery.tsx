import "./ImageAssetGallery.css";
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
  items: ImageAssetGalleryItem[];
  onSelect: (index: number) => void;
  selectedIndex: number;
}

export function ImageAssetGallery({ items, onSelect, selectedIndex }: ImageAssetGalleryProps) {
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
          <span className="image-asset-card__media">
            {item.imageSrc ? (
              <img alt="" decoding="async" loading="lazy" src={item.imageSrc} />
            ) : (
              <ImageIcon aria-hidden className="image-asset-card__fallback" />
            )}
          </span>
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
