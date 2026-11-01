import type { CSSProperties } from "react";

import { Dialog } from "./Dialog";
import { VisualMedia } from "./VisualMedia";
import "./MediaPreviewDialog.css";

export interface MediaPreview {
  src: string;
  title: string;
  autoPlay?: boolean;
  playbackRate?: number;
}

interface Props {
  media: MediaPreview | null;
  onClose: () => void;
  closeLabel: string;
  backgroundColor?: string;
}

export function MediaPreviewDialog({ media, onClose, closeLabel, backgroundColor }: Props) {
  return (
    <Dialog
      className="media-preview"
      bodyClassName="media-preview__body"
      closeLabel={closeLabel}
      closeOnBackdrop
      trapFocus
      open={Boolean(media)}
      onClose={onClose}
      title={media?.title ?? ""}
    >
      <div
        className="media-preview__canvas"
        data-colored-background={Boolean(backgroundColor) || undefined}
        style={{ "--media-preview-background": backgroundColor } as CSSProperties}
        onClick={(event) => {
          if (event.target === event.currentTarget) onClose();
        }}
      >
        {media ? (
          <VisualMedia
            key={media.src}
            src={media.src}
            alt={media.title}
            autoPlay={media.autoPlay}
            playbackRate={media.playbackRate}
            loading="eager"
          />
        ) : null}
      </div>
    </Dialog>
  );
}
