import { useRef, useState } from "react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";

export function SpriteVideoFramePicker({
  path,
  frameTime,
  disabled,
  title,
  onCapture,
}: {
  path: string;
  frameTime: number;
  disabled: boolean;
  title: string;
  onCapture: (seconds: number) => void;
}) {
  const { t } = useI18n();
  const video = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [seconds, setSeconds] = useState(frameTime);
  return (
    <details className="sprite-generation__video">
      <summary>{t("spriteGeneration.chooseFrame")}</summary>
      <p className="sprite-generation__hint">{t("spriteGeneration.frameHint")}</p>
      <video
        aria-label={`${title} ${t("spriteGeneration.video")}`}
        controls
        muted
        playsInline
        preload="metadata"
        ref={video}
        src={fileUrl(path)}
        onLoadedMetadata={(event) => {
          const media = event.currentTarget;
          media.currentTime = Math.min(frameTime, Number.isFinite(media.duration) ? media.duration : frameTime);
          setReady(true);
        }}
        onTimeUpdate={(event) => setSeconds(event.currentTarget.currentTime)}
        onError={() => setFailed(true)}
      />
      {failed ? <p className="sprite-generation__hint">{t("spriteGeneration.videoUnavailable")}</p> : null}
      <Button
        disabled={disabled || !ready || failed}
        onClick={() => {
          if (!video.current) return;
          video.current.pause();
          onCapture(video.current.currentTime);
        }}
      >
        {t("spriteGeneration.captureFrame", { seconds: seconds.toFixed(2) })}
      </Button>
    </details>
  );
}
