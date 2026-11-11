import { useEffect, useRef, useState } from "react";

import type { MouthPose, SpriteMouthManifest } from "../../shared/assets/spriteMouth";
import { avatarAssetUrl } from "./assetUrl";
import { VisualMedia, type VisualMediaElement, type VisualMediaProps } from "../../shared/ui/VisualMedia";
import { bindMouthLevel } from "./voiceRoute";
import { mouthPatchMatrix, mouthPose } from "./spriteMouthMath";
import "./SpriteMouthMedia.css";

interface Props extends VisualMediaProps {
  mouthSync?: string;
  mouthProfile?: SpriteMouthManifest;
  voiceCharacterName?: string;
  previewSpeaking?: boolean;
}

const profiles = new Map<string, Promise<SpriteMouthManifest>>();
const pictures = new Map<string, Promise<HTMLImageElement>>();

function loadProfile(path: string) {
  let cached = profiles.get(path);
  if (!cached) {
    const requestUrl = new URL(path, window.location.href);
    if (requestUrl.pathname === "/api/media") requestUrl.pathname = "/api/characters/sprites/mouth/profile";
    cached = fetch(requestUrl.toString())
      .then(async (response) => {
        if (!response.ok) throw new Error("Mouth profile unavailable");
        const profile = (await response.json()) as SpriteMouthManifest;
        if (profile.version !== 1 || !profile.track?.length) throw new Error("Mouth profile unavailable");
        return {
          ...profile,
          mouths: {
            closed: avatarAssetUrl(path, profile.mouths.closed),
            half: avatarAssetUrl(path, profile.mouths.half),
            open: avatarAssetUrl(path, profile.mouths.open),
          },
        };
      })
      .catch((error) => {
        profiles.delete(path);
        throw error;
      });
    if (profiles.size >= 32) profiles.delete(profiles.keys().next().value!);
    profiles.set(path, cached);
  }
  return cached;
}

function picture(path: string) {
  const url = path;
  let cached = pictures.get(url);
  if (!cached) {
    cached = new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => {
        pictures.delete(url);
        reject(new Error("Mouth image unavailable"));
      };
      image.src = url;
    });
    if (pictures.size >= 96) pictures.delete(pictures.keys().next().value!);
    pictures.set(url, cached);
  }
  return cached;
}

export function SpriteMouthMedia(props: Props) {
  if (!props.mouthSync && !props.mouthProfile) {
    const {
      mouthSync: _sync,
      mouthProfile: _profile,
      voiceCharacterName: _voice,
      previewSpeaking: _preview,
      ...media
    } = props;
    return <VisualMedia {...media} />;
  }
  return <BoundMouthMedia {...props} key={props.src} />;
}

function BoundMouthMedia({
  mouthSync,
  mouthProfile,
  voiceCharacterName,
  previewSpeaking,
  className,
  style,
  hitbox,
  onMouseDown,
  onFrameReady,
  ...media
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const level = useRef(0);
  const [element, setElement] = useState<VisualMediaElement | null>(null);
  const [profile, setProfile] = useState<SpriteMouthManifest | null>(mouthProfile ?? null);
  const active = media.active !== false;

  useEffect(() => {
    if (!voiceCharacterName || !active) {
      level.current = 0;
      return;
    }
    return bindMouthLevel(voiceCharacterName, (value) => {
      level.current = value;
    });
  }, [voiceCharacterName, active]);

  useEffect(() => {
    let cancelled = false;
    setProfile(mouthProfile ?? null);
    if (!mouthProfile && mouthSync)
      void loadProfile(mouthSync).then(
        (result) => {
          if (!cancelled) setProfile(result);
        },
        () => {
          if (!cancelled) setProfile(null);
        },
      );
    return () => {
      cancelled = true;
    };
  }, [mouthSync, mouthProfile]);

  useEffect(() => {
    const surface = canvas.current;
    if (!surface || !profile || !element) return;
    const context = surface.getContext("2d");
    if (!context) return;
    let stopped = false;
    let frame = 0;
    let videoFrame: number | undefined;
    let mediaTime = element instanceof HTMLVideoElement ? element.currentTime : 0;
    let pose: MouthPose = "closed";
    let lastChange = 0;
    surface.width = profile.width;
    surface.height = profile.height;
    const video = element instanceof HTMLVideoElement ? element : null;
    const presented = (_now: number, metadata: VideoFrameCallbackMetadata) => {
      mediaTime = metadata.mediaTime;
      if (!stopped) videoFrame = video?.requestVideoFrameCallback(presented);
    };
    if (video?.requestVideoFrameCallback) videoFrame = video.requestVideoFrameCallback(presented);
    void Promise.all([picture(profile.mouths.closed), picture(profile.mouths.half), picture(profile.mouths.open)])
      .then(([closed, half, open]) => {
        if (stopped) return;
        const images = { closed, half, open };
        const draw = (now: number) => {
          if (stopped) return;
          const drive = previewSpeaking ? Math.max(0, Math.sin(now / 110)) : level.current;
          const next = mouthPose(drive, pose, profile.correction.gain);
          if (next === "closed" || now - lastChange >= 65) {
            if (pose !== next) lastChange = now;
            pose = next;
          }
          if (video && !video.requestVideoFrameCallback) mediaTime = video.currentTime;
          context.setTransform(1, 0, 0, 1, 0, 0);
          context.clearRect(0, 0, surface.width, surface.height);
          if (active) {
            context.setTransform(...mouthPatchMatrix(profile, mediaTime));
            context.drawImage(images[pose], 0, 0);
          }
          frame = requestAnimationFrame(draw);
        };
        frame = requestAnimationFrame(draw);
      })
      .catch(() => {
        /* Keep the original media usable when optional mouth assets are missing. */
      });
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      if (videoFrame !== undefined) video?.cancelVideoFrameCallback(videoFrame);
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, surface.width, surface.height);
    };
  }, [profile, element, active, previewSpeaking]);

  return (
    <div
      className={`${className ?? ""} sprite-mouth-media`}
      style={style}
      data-chat-stage-hitbox={hitbox ? "true" : undefined}
      onMouseDown={onMouseDown}
    >
      <VisualMedia
        {...media}
        className="sprite-mouth-media__base"
        onFrameReady={(ready) => {
          setElement(ready);
          onFrameReady?.(ready);
        }}
      />
      <canvas ref={canvas} className="sprite-mouth-media__overlay" aria-hidden />
    </div>
  );
}
