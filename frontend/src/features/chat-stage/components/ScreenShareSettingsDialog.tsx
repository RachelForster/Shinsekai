import { useEffect, useRef, useState, type PointerEvent } from "react";

import { useI18n } from "../../../shared/i18n";
import type { ScreenOcrRegion, ScreenOcrScope, ScreenPlaybackAudioState } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";
import { ChatStageModal } from "./ChatStageModal";

type Point = { x: number; y: number };

const playbackAudioLabels = {
  unavailable: "chat.perception.audioUnavailable",
  playing: "chat.perception.audioPlaying",
  quiet: "chat.perception.audioQuiet",
  stopped: "chat.perception.audioStopped",
} as const;

function previewPoint(event: PointerEvent<HTMLDivElement>): Point {
  const rect = event.currentTarget.getBoundingClientRect();
  return {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  };
}

function selectionBetween(start: Point, end: Point): ScreenOcrRegion {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(start.x - end.x),
    height: Math.abs(start.y - end.y),
  };
}

export function ScreenShareSettingsDialog({
  ocrEnabled,
  onClose,
  onScopeChange,
  playbackAudio = "unavailable",
  proactiveEnabled = false,
  scope,
  stream,
}: {
  ocrEnabled: boolean;
  onClose: () => void;
  onScopeChange: (scope: ScreenOcrScope) => void;
  playbackAudio?: ScreenPlaybackAudioState;
  proactiveEnabled?: boolean;
  scope: ScreenOcrScope;
  stream: MediaStream;
}) {
  const { t } = useI18n();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const startRef = useRef<{ point: Point; pointerId: number } | null>(null);
  const [aspectRatio, setAspectRatio] = useState<number | null>(null);
  const [drawing, setDrawing] = useState<ScreenOcrRegion | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = stream;
    void video.play().catch(() => {});
    return () => {
      video.pause();
      video.srcObject = null;
    };
  }, [stream]);

  function updateAspectRatio() {
    const video = videoRef.current;
    if (video?.videoWidth && video.videoHeight) {
      setAspectRatio(video.videoWidth / video.videoHeight);
    }
  }

  function startSelection(event: PointerEvent<HTMLDivElement>) {
    if (!ocrEnabled || !aspectRatio || event.button !== 0 || startRef.current) return;
    const point = previewPoint(event);
    startRef.current = { point, pointerId: event.pointerId };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDrawing(selectionBetween(point, point));
  }

  function moveSelection(event: PointerEvent<HTMLDivElement>) {
    const start = startRef.current;
    if (start && start.pointerId === event.pointerId) {
      setDrawing(selectionBetween(start.point, previewPoint(event)));
    }
  }

  function finishSelection(event: PointerEvent<HTMLDivElement>) {
    const start = startRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const region = selectionBetween(start.point, previewPoint(event));
    startRef.current = null;
    setDrawing(null);
    if (region.width >= 0.01 && region.height >= 0.01) {
      onScopeChange({ mode: "region", region });
    }
  }

  const region = drawing ?? (scope.mode === "region" ? scope.region : null);
  const ratio = aspectRatio ?? 16 / 9;
  return (
    <ChatStageModal
      backdropClassName="screen-share-settings-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="screen-share-settings-dialog"
      dialogId="chat-screen-share-settings"
      labelledBy="chat-screen-share-settings-title"
      onClose={onClose}
      open
      title={t("chat.perception.screenSettings")}
    >
      <div className="screen-share-settings__body">
        <div className="screen-share-settings__modes">
          <Button
            aria-pressed={scope.mode === "bottom"}
            disabled={!ocrEnabled}
            onClick={() => onScopeChange({ mode: "bottom" })}
            variant={scope.mode === "bottom" ? "primary" : "default"}
          >
            {t("chat.perception.ocrBottom")}
          </Button>
          <Button
            aria-pressed={scope.mode === "full"}
            disabled={!ocrEnabled}
            onClick={() => onScopeChange({ mode: "full" })}
            variant={scope.mode === "full" ? "primary" : "default"}
          >
            {t("chat.perception.ocrFull")}
          </Button>
          {scope.mode === "region" ? <span role="status">{t("chat.perception.ocrRegion")}</span> : null}
        </div>
        <div
          aria-label={t("chat.perception.screenPreview")}
          className="screen-share-settings__preview"
          data-selectable={ocrEnabled && Boolean(aspectRatio)}
          onLostPointerCapture={() => {
            startRef.current = null;
            setDrawing(null);
          }}
          onPointerDown={startSelection}
          onPointerMove={moveSelection}
          onPointerUp={finishSelection}
          role="group"
          style={{ aspectRatio: ratio, width: `min(100%, ${ratio * 48}vh)` }}
        >
          <video
            aria-hidden="true"
            autoPlay
            muted
            onLoadedMetadata={updateAspectRatio}
            onResize={updateAspectRatio}
            playsInline
            ref={videoRef}
          />
          {region ? (
            <span
              aria-hidden="true"
              className="screen-share-settings__selection"
              style={{
                left: `${region.x * 100}%`,
                top: `${region.y * 100}%`,
                width: `${region.width * 100}%`,
                height: `${region.height * 100}%`,
              }}
            />
          ) : null}
        </div>
        <p className="screen-share-settings__hint">
          {t(ocrEnabled ? "chat.perception.ocrDragHint" : "chat.perception.ocrDisabledHint")}
        </p>
        {proactiveEnabled ? (
          <p className="screen-share-settings__hint">{t(playbackAudioLabels[playbackAudio])}</p>
        ) : null}
      </div>
    </ChatStageModal>
  );
}
