import { useEffect, useRef, useState, type MouseEventHandler, type SyntheticEvent } from "react";

import { isMp4Media } from "../assets/visualMedia";

export type VisualMediaElement = HTMLImageElement | HTMLVideoElement;

interface VisualMediaProps {
  src: string;
  alt: string;
  active?: boolean;
  autoPlay?: boolean;
  className?: string;
  decoding?: "async" | "auto" | "sync";
  errorMessage?: string;
  hitbox?: boolean;
  loading?: "eager" | "lazy";
  onDimensions?: (width: number, height: number) => void;
  onError?: (event: SyntheticEvent<VisualMediaElement>) => void;
  onLoad?: (event: SyntheticEvent<VisualMediaElement>) => void;
  onMouseDown?: MouseEventHandler<HTMLElement>;
}

/** File-based visuals share layout and tags, while videos own their playback. */
export function VisualMedia(props: VisualMediaProps) {
  if (isMp4Media(props.src)) return <VideoVisual {...props} key={props.src} />;
  const {
    src,
    alt,
    className,
    decoding = "async",
    hitbox,
    loading,
    onDimensions,
    onError,
    onLoad,
    onMouseDown,
  } = props;
  return (
    <img
      alt={alt}
      className={className}
      data-chat-stage-hitbox={hitbox ? "true" : undefined}
      decoding={decoding}
      loading={loading}
      onError={onError}
      onLoad={(event) => {
        onDimensions?.(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight);
        onLoad?.(event);
      }}
      onMouseDown={onMouseDown}
      src={src}
    />
  );
}

function VideoVisual({
  src,
  alt,
  active = true,
  autoPlay = true,
  className,
  errorMessage = "Unable to play this video.",
  hitbox,
  loading,
  onDimensions,
  onError,
  onLoad,
  onMouseDown,
}: VisualMediaProps) {
  const [failed, setFailed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const wantedRef = useRef(false);
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
    // Restore the source during React StrictMode's setup/cleanup replay too.
    video.setAttribute("src", src);
    video.load();
    return () => {
      wantedRef.current = false;
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [inView, src, failed]);

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
        () => {},
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
      loop={autoPlay}
      muted
      onError={(event) => {
        event.currentTarget.dataset.loadState = "error";
        setFailed(true);
        onError?.(event);
      }}
      onLoadedData={onLoad}
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
      preload="metadata"
    />
  );
}
