import { useEffect, useRef, useState, type CSSProperties, type MouseEventHandler, type SyntheticEvent } from "react";

import { isVideoMedia } from "../assets/visualMedia";

export type VisualMediaElement = HTMLImageElement | HTMLVideoElement;

export interface VisualMediaProps {
  src: string;
  alt: string;
  active?: boolean;
  autoPlay?: boolean;
  loop?: boolean;
  playbackRate?: number;
  onEnded?: () => void;
  onPlayBlocked?: () => void;
  className?: string;
  decoding?: "async" | "auto" | "sync";
  errorMessage?: string;
  hitbox?: boolean;
  loading?: "eager" | "lazy";
  preload?: "none" | "metadata" | "auto";
  style?: CSSProperties;
  onDimensions?: (width: number, height: number) => void;
  onError?: (event: SyntheticEvent<VisualMediaElement>) => void;
  onLoad?: (event: SyntheticEvent<VisualMediaElement>) => void;
  /** The first decoded frame is ready to replace another visible surface. */
  onFrameReady?: (element: VisualMediaElement) => void;
  onMouseDown?: MouseEventHandler<HTMLElement>;
}

/** File-based visuals share layout and tags, while videos own their playback. */
export function VisualMedia(props: VisualMediaProps) {
  if (isVideoMedia(props.src)) return <VideoVisual {...props} key={props.src} />;
  const {
    src,
    alt,
    className,
    decoding = "async",
    hitbox,
    loading,
    style,
    onDimensions,
    onError,
    onLoad,
    onFrameReady,
    onMouseDown,
  } = props;
  return (
    <img
      alt={alt}
      className={className}
      data-chat-stage-hitbox={hitbox ? "true" : undefined}
      decoding={decoding}
      draggable={false}
      loading={loading}
      onError={onError}
      onLoad={(event) => {
        const image = event.currentTarget;
        onDimensions?.(image.naturalWidth, image.naturalHeight);
        onLoad?.(event);
        if (onFrameReady) {
          if (image.decode)
            void image.decode().then(
              () => {
                if (image.isConnected) onFrameReady(image);
              },
              () => {},
            );
          else onFrameReady(image);
        }
      }}
      onMouseDown={onMouseDown}
      src={src}
      style={style}
    />
  );
}

function VideoVisual({
  src,
  alt,
  active = true,
  autoPlay = true,
  loop = autoPlay,
  playbackRate = 1,
  onEnded,
  onPlayBlocked,
  className,
  errorMessage = "Unable to play this video.",
  hitbox,
  loading,
  preload = "metadata",
  style,
  onDimensions,
  onError,
  onLoad,
  onFrameReady,
  onMouseDown,
}: VisualMediaProps) {
  const [failed, setFailed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const wantedRef = useRef(false);
  const blockedRef = useRef(onPlayBlocked);
  blockedRef.current = onPlayBlocked;
  const frameReadyRef = useRef(onFrameReady);
  frameReadyRef.current = onFrameReady;
  const [pageVisible, setPageVisible] = useState(document.visibilityState !== "hidden");
  const [inView, setInView] = useState(loading !== "lazy" || typeof IntersectionObserver === "undefined");
  const shouldPlay = autoPlay && active && pageVisible && inView && !failed;

  useEffect(() => {
    const changed = () => setPageVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || failed) return;
    if (loading !== "lazy" || typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      setInView(entries.some((entry) => entry.isIntersecting));
    });
    observer.observe(video);
    return () => observer.disconnect();
  }, [loading, failed]);

  useEffect(() => {
    const video = videoRef.current;
    if (!inView || !video || failed) return;
    // loadeddata can precede presentation. Keep the old surface until the
    // compositor has a decoded frame, including paused, preloaded targets.
    let cancelled = false;
    const frameCallback =
      frameReadyRef.current && video.requestVideoFrameCallback
        ? video.requestVideoFrameCallback(() => {
            if (!cancelled) frameReadyRef.current?.(video);
          })
        : undefined;
    // Restore the source during React StrictMode's setup/cleanup replay too.
    video.setAttribute("src", src);
    video.load();
    return () => {
      cancelled = true;
      if (frameCallback !== undefined) video.cancelVideoFrameCallback(frameCallback);
      wantedRef.current = false;
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [inView, src, failed]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.defaultPlaybackRate = playbackRate;
    video.playbackRate = playbackRate;
  }, [playbackRate]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    wantedRef.current = shouldPlay;
    video.muted = true;
    if (shouldPlay) {
      // A blocked autoplay request must never delay dialogue or reject unhandled.
      void video.play()?.then(
        () => {
          if (!wantedRef.current) video.pause();
        },
        () => {
          if (wantedRef.current) blockedRef.current?.();
        },
      );
    } else {
      video.pause();
    }
    return () => {
      wantedRef.current = false;
      video.pause();
    };
  }, [shouldPlay]);

  if (failed && !onError) return <span role="status">{errorMessage}</span>;
  return (
    <video
      ref={videoRef}
      aria-label={alt || undefined}
      aria-hidden={alt ? undefined : true}
      autoPlay={shouldPlay}
      className={className}
      data-chat-stage-hitbox={hitbox ? "true" : undefined}
      disablePictureInPicture
      draggable={false}
      loop={loop}
      muted
      onError={(event) => {
        event.currentTarget.dataset.loadState = "error";
        setFailed(true);
        onError?.(event);
      }}
      onLoadedData={(event) => {
        onLoad?.(event);
        if (!event.currentTarget.requestVideoFrameCallback) frameReadyRef.current?.(event.currentTarget);
      }}
      onEnded={onEnded}
      onLoadedMetadata={(event) => {
        const video = event.currentTarget;
        onDimensions?.(video.videoWidth, video.videoHeight);
        // Decode one cover frame for paused thumbnails, including Safari.
        if (!autoPlay && Number.isFinite(video.duration) && video.duration > 0) {
          video.currentTime = Math.min(0.001, video.duration / 2);
        }
      }}
      onMouseDown={onMouseDown}
      playsInline
      preload={preload}
      style={style}
    />
  );
}
