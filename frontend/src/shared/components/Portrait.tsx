import { useState, type CSSProperties, type PointerEventHandler } from "react";
import type { PortraitCrop } from "../platform/types";
import { stageAssetUrl } from "../../features/chat-stage/chatStageUtils";

export const defaultPortraitCrop: PortraitCrop = { x: 0.5, y: 0.2, zoom: 1 };

export function portraitGeometry(width: number, height: number, crop: PortraitCrop) {
  const side = Math.min(width, height) / Math.max(1, Math.min(8, crop.zoom));
  const left = Math.max(0, Math.min(width - side, crop.x * width - side / 2));
  const top = Math.max(0, Math.min(height - side, crop.y * height - side / 2));
  return { side, left, top };
}

export function Portrait({
  path,
  crop = defaultPortraitCrop,
  name,
  size = "100%",
  onPointerDown,
  onPointerMove,
  onImageSize,
}: {
  path: string;
  crop?: PortraitCrop;
  name: string;
  size?: CSSProperties["width"];
  onPointerDown?: PointerEventHandler<HTMLDivElement>;
  onPointerMove?: PointerEventHandler<HTMLDivElement>;
  onImageSize?: (width: number, height: number) => void;
}) {
  const [image, setImage] = useState({ path: "", width: 1, height: 1 });
  const geometry = portraitGeometry(image.width, image.height, crop);
  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      style={{
        width: size,
        aspectRatio: "1",
        position: "relative",
        overflow: "hidden",
        touchAction: onPointerDown ? "none" : undefined,
        background: "transparent",
      }}
    >
      <img
        src={stageAssetUrl(path)}
        alt={name}
        draggable={false}
        onLoad={(event) => {
          const { naturalWidth: width, naturalHeight: height } = event.currentTarget;
          setImage({ path, width, height });
          onImageSize?.(width, height);
        }}
        style={{
          position: "absolute",
          maxWidth: "none",
          width: `${(image.width / geometry.side) * 100}%`,
          height: `${(image.height / geometry.side) * 100}%`,
          left: `${(-geometry.left / geometry.side) * 100}%`,
          top: `${(-geometry.top / geometry.side) * 100}%`,
          visibility: image.path === path ? "visible" : "hidden",
          pointerEvents: "none",
        }}
      />
    </div>
  );
}
