import { useEffect, useRef, useState } from "react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { MouthPose } from "../../shared/platform/types";
import { Button } from "../../shared/ui";

export interface MouthFrame {
  index: number;
  path: string;
  time?: number;
}
export function mouthFrameAtTime(frames: MouthFrame[], time: number, fps = 24): number {
  let low = 0,
    high = frames.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if ((frames[middle].time ?? frames[middle].index / fps) <= time + 0.000001) low = middle;
    else high = middle - 1;
  }
  return low;
}

export function SpriteMouthTimeline({
  src,
  frames,
  fps = 24,
  disabled,
  requestedFrame,
  onPick,
}: {
  src: string;
  frames: MouthFrame[];
  fps?: number;
  disabled: boolean;
  requestedFrame?: { index: number; sequence: number };
  onPick: (pose: MouthPose, index: number) => void;
}) {
  const { t } = useI18n();
  const video = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<number | null>(null);
  const [position, setPosition] = useState(0);
  const actualFps = Number.isFinite(fps) && fps > 0 ? fps : 24;
  const syncTime = (time: number) => {
    const next = mouthFrameAtTime(frames, time, actualFps);
    if (pendingSeek.current !== null) {
      if (next !== pendingSeek.current) return;
      pendingSeek.current = null;
    }
    setPosition(next);
  };
  const seek = (value: number) => {
    const next = Math.max(0, Math.min(frames.length - 1, value));
    const frame = frames[next];
    if (!frame) return;
    const time = frame.time ?? frame.index / actualFps;
    const interval = frames[next + 1]?.time === undefined ? 1 / actualFps : frames[next + 1].time! - time;
    const player = video.current;
    pendingSeek.current = next;
    if (player) {
      player.pause();
      player.currentTime = time + Math.max(0.0001, interval * 0.2);
    }
    setPosition(next);
  };
  useEffect(() => {
    const player = video.current;
    if (!player?.requestVideoFrameCallback) return;
    let callback: number;
    const presented = (_now: number, metadata: VideoFrameCallbackMetadata) => {
      syncTime(metadata.mediaTime);
      callback = player.requestVideoFrameCallback(presented);
    };
    callback = player.requestVideoFrameCallback(presented);
    return () => player.cancelVideoFrameCallback(callback);
  }, [src, frames, actualFps]);
  useEffect(() => {
    if (requestedFrame) seek(frames.findIndex((frame) => frame.index === requestedFrame.index));
  }, [requestedFrame]);
  const current = frames[position];
  useEffect(() => {
    const player = video.current;
    if (!player) return;
    player.setAttribute("src", fileUrl(src));
    return () => {
      player.pause();
      player.removeAttribute("src");
      player.load();
    };
  }, [src]);
  return (
    <div className="sprite-mouth-timeline">
      <video
        ref={video}
        className="sprite-mouth-editor__speech"
        controls
        muted
        playsInline
        src={fileUrl(src)}
        onLoadedMetadata={(event) => {
          event.currentTarget.playbackRate = 0.5;
          if (pendingSeek.current !== null) seek(pendingSeek.current);
          else syncTime(event.currentTarget.currentTime);
        }}
        onPlay={() => {
          pendingSeek.current = null;
        }}
        onTimeUpdate={(event) => {
          if (!event.currentTarget.requestVideoFrameCallback) syncTime(event.currentTarget.currentTime);
        }}
        onSeeked={(event) => {
          if (!event.currentTarget.requestVideoFrameCallback) syncTime(event.currentTarget.currentTime);
        }}
      />
      {frames.length ? (
        <>
          <div className="sprite-mouth-timeline__position">
            <Button
              aria-label={t("spriteMouth.previousFrame")}
              disabled={position <= 0}
              onClick={() => seek(position - 1)}
            >
              ←
            </Button>
            <output aria-live="off">
              {t("spriteMouth.currentFrame", { current: (current?.index ?? 0) + 1, total: frames.length })}
            </output>
            <Button
              aria-label={t("spriteMouth.nextFrame")}
              disabled={position >= frames.length - 1}
              onClick={() => seek(position + 1)}
            >
              →
            </Button>
          </div>
          <input
            type="range"
            min={0}
            max={frames.length - 1}
            step={1}
            value={position}
            aria-label={t("spriteMouth.seekFrame")}
            onChange={(event) => seek(Number(event.target.value))}
          />
          <div className="sprite-mouth-actions">
            {(["closed", "half", "open"] as const).map((pose) => (
              <Button key={pose} disabled={disabled || !current} onClick={() => current && onPick(pose, current.index)}>
                {t("spriteMouth.useCurrentFrame", { pose: t(`spriteMouth.${pose}`) })}
              </Button>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
