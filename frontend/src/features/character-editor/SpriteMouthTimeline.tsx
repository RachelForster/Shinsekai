import { useEffect, useRef, useState } from "react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { MouthPose, SpriteEyeFrames } from "../../shared/platform/types";
import { Button, Select } from "../../shared/ui";

const eyePoses = ["open", "half", "closed"] as const;

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
  savedEyeFrames,
  onSaveEyes,
}: {
  src: string;
  frames: MouthFrame[];
  fps?: number;
  disabled: boolean;
  requestedFrame?: { index: number; sequence: number };
  onPick: (pose: MouthPose, index: number) => void;
  savedEyeFrames?: SpriteEyeFrames;
  onSaveEyes?: (frames: SpriteEyeFrames) => void;
}) {
  const { t } = useI18n();
  const video = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<number | null>(null);
  const [position, setPosition] = useState(0);
  const [canExport, setCanExport] = useState(false);
  const [exportFailed, setExportFailed] = useState(false);
  const [eyeDraft, setEyeDraft] = useState<SpriteEyeFrames>();
  const eyeFrames = eyeDraft ?? savedEyeFrames;
  const eyesChanged = eyePoses.some((pose) => eyeFrames?.[pose] !== savedEyeFrames?.[pose]);
  const hasSavedEyes = eyePoses.some((pose) => savedEyeFrames?.[pose] !== undefined);
  const actualFps = Number.isFinite(fps) && fps > 0 ? fps : 24;
  const frameAvailable = (player: HTMLVideoElement) =>
    player.paused && !player.seeking && player.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA;
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
    setCanExport(false);
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
  const exportEyeFrame = (pose: MouthPose) => {
    const player = video.current;
    if (
      !current ||
      !player ||
      !frameAvailable(player) ||
      mouthFrameAtTime(frames, player.currentTime, actualFps) !== position
    )
      return;
    setExportFailed(false);
    const canvas = document.createElement("canvas");
    canvas.width = player.videoWidth;
    canvas.height = player.videoHeight;
    const context = canvas.getContext("2d");
    if (!context || !canvas.width || !canvas.height) {
      setExportFailed(true);
      return;
    }
    try {
      context.drawImage(player, 0, 0);
      canvas.toBlob((blob) => {
        if (!blob) {
          setExportFailed(true);
          return;
        }
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `eyes-${pose}-frame-${current.index + 1}.png`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      }, "image/png");
    } catch {
      setExportFailed(true);
    }
  };
  useEffect(() => {
    const player = video.current;
    if (!player) return;
    setCanExport(false);
    setExportFailed(false);
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
        crossOrigin="anonymous"
        src={fileUrl(src)}
        onLoadedMetadata={(event) => {
          event.currentTarget.playbackRate = 0.5;
          if (pendingSeek.current !== null) seek(pendingSeek.current);
          else syncTime(event.currentTarget.currentTime);
        }}
        onPlay={() => {
          pendingSeek.current = null;
          setCanExport(false);
        }}
        onPause={(event) => setCanExport(frameAvailable(event.currentTarget))}
        onSeeking={() => setCanExport(false)}
        onLoadedData={(event) => setCanExport(frameAvailable(event.currentTarget))}
        onTimeUpdate={(event) => {
          if (!event.currentTarget.requestVideoFrameCallback) syncTime(event.currentTarget.currentTime);
        }}
        onSeeked={(event) => {
          if (!event.currentTarget.requestVideoFrameCallback) syncTime(event.currentTarget.currentTime);
          setCanExport(frameAvailable(event.currentTarget));
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
          <details open={eyePoses.some((pose) => eyeFrames?.[pose] !== undefined) || undefined}>
            <summary>{t("spriteMouth.eyeFrames")}</summary>
            <p className="sprite-generation__hint">
              {t(onSaveEyes ? "spriteMouth.eyeFramesHint" : "spriteMouth.eyeSaveNeedsMouth")}
            </p>
            <div className="sprite-mouth-editor__poses">
              {eyePoses.map((pose) => {
                const chosen = frames.findIndex((frame) => frame.index === eyeFrames?.[pose]);
                const label = t(`spriteMouth.eyePose.${pose}`);
                return (
                  <label key={pose}>
                    {label}
                    {chosen >= 0 ? (
                      <button
                        type="button"
                        className="sprite-mouth-editor__pose-frame"
                        aria-label={t("spriteMouth.previewFrame", { pose: label })}
                        onClick={() => seek(chosen)}
                      >
                        <img alt="" src={fileUrl(frames[chosen].path)} />
                      </button>
                    ) : null}
                    <Select
                      aria-label={label}
                      disabled={disabled || !onSaveEyes}
                      value={chosen < 0 ? "" : frames[chosen].index}
                      onChange={(event) => {
                        const next = { ...eyeFrames };
                        if (event.target.value === "") delete next[pose];
                        else {
                          next[pose] = Number(event.target.value);
                          seek(frames.findIndex((frame) => frame.index === next[pose]));
                        }
                        setEyeDraft(next);
                      }}
                    >
                      <option value="">{t("spriteMouth.eyeUnselected")}</option>
                      {frames.map((frame) => (
                        <option
                          key={frame.index}
                          value={frame.index}
                          disabled={eyePoses.some((other) => other !== pose && eyeFrames?.[other] === frame.index)}
                        >
                          {t("spriteMouth.frame", { n: frame.index + 1 })}
                        </option>
                      ))}
                    </Select>
                  </label>
                );
              })}
            </div>
            {onSaveEyes ? (
              <div className="sprite-mouth-actions">
                <Button disabled={disabled || !eyesChanged} onClick={() => onSaveEyes(eyeDraft ?? {})}>
                  {t("spriteMouth.eyeSave")}
                </Button>
                {hasSavedEyes ? (
                  <Button
                    variant="ghost"
                    disabled={disabled}
                    onClick={() => {
                      setEyeDraft({});
                      onSaveEyes({});
                    }}
                  >
                    {t("spriteMouth.eyeClear")}
                  </Button>
                ) : null}
                {hasSavedEyes && !eyesChanged ? <span role="status">{t("spriteMouth.saved")}</span> : null}
              </div>
            ) : null}
            <div className="sprite-mouth-actions">
              {eyePoses.map((pose) => (
                <Button key={pose} disabled={!current || !canExport} onClick={() => exportEyeFrame(pose)}>
                  {t(`spriteMouth.eyeExport.${pose}`)}
                </Button>
              ))}
            </div>
            {exportFailed ? <p role="alert">{t("spriteMouth.eyeExportFailed")}</p> : null}
          </details>
        </>
      ) : null}
    </div>
  );
}
