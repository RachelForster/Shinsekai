import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ChangeEvent } from "react";
import { LoaderCircle, Pause, Play, Volume2, VolumeX } from "lucide-react";

import "./AudioPlayer.css";

const AUDIO_PLAYER_ACTIVE_EVENT = "shinsekai-audio-player-active";
const AUDIO_PLAYER_WARMUP_EVENT = "shinsekai-audio-player-warmup";
const HAVE_FUTURE_DATA = 3;
let activeAudioPlayerId: string | null = null;
let warmedAudioPlayerId: string | null = null;
let nextAudioPlayerId = 0;

interface AudioPlayerProps {
  className?: string;
  compact?: boolean;
  label?: string;
  preload?: "auto" | "metadata" | "none";
  src: string;
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "0:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function rangeStyle(percent: number) {
  return { "--audio-progress": `${Math.max(0, Math.min(100, percent))}%` } as CSSProperties;
}

function isActiveAudioEvent(event: Event): event is CustomEvent<{ id: string }> {
  return event instanceof CustomEvent && typeof event.detail?.id === "string";
}

function preloadRank(preload: HTMLMediaElement["preload"]) {
  if (preload === "auto") {
    return 2;
  }
  if (preload === "metadata") {
    return 1;
  }
  return 0;
}

function setNativeAudioSource(audio: HTMLAudioElement, src: string, preload: HTMLMediaElement["preload"]) {
  const previousPreload = audio.preload;
  audio.preload = preload;
  if (audio.getAttribute("src") !== src) {
    audio.setAttribute("src", src);
    audio.load();
    return;
  }
  if (preloadRank(preload) > preloadRank(previousPreload) && audio.readyState < HAVE_FUTURE_DATA) {
    audio.load();
  }
}

function releaseNativeAudio(audio: HTMLAudioElement) {
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

function activateAudioPlayer(id: string) {
  activeAudioPlayerId = id;
  warmedAudioPlayerId = null;
  window.dispatchEvent(new CustomEvent(AUDIO_PLAYER_ACTIVE_EVENT, { detail: { id } }));
}

function warmupAudioPlayer(id: string) {
  warmedAudioPlayerId = id;
  window.dispatchEvent(new CustomEvent(AUDIO_PLAYER_WARMUP_EVENT, { detail: { id } }));
}

function releaseActiveAudioPlayer(id: string) {
  if (activeAudioPlayerId === id) {
    activeAudioPlayerId = null;
  }
}

function releaseWarmedAudioPlayer(id: string) {
  if (warmedAudioPlayerId === id) {
    warmedAudioPlayerId = null;
  }
}

export function AudioPlayer({
  className = "",
  compact = false,
  label = "Audio",
  preload = "none",
  src,
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const mountedRef = useRef(true);
  const playRequestRef = useRef(0);
  const playerIdRef = useRef("");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isActive, setIsActive] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(0.9);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
  const volumePercent = isMuted ? 0 : volume * 100;
  const playerClassName = ["audio-player", compact ? "audio-player--compact" : "", className].filter(Boolean).join(" ");
  if (!playerIdRef.current) {
    nextAudioPlayerId += 1;
    playerIdRef.current = `audio-player-${nextAudioPlayerId}`;
  }

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.pause();
    if (src && preload !== "none") {
      setNativeAudioSource(audio, src, preload);
    } else {
      releaseNativeAudio(audio);
    }
    setCurrentTime(0);
    setDuration(0);
    setHasError(false);
    setIsActive(false);
    setIsLoading(false);
    setIsPlaying(false);
    releaseActiveAudioPlayer(playerIdRef.current);
    releaseWarmedAudioPlayer(playerIdRef.current);
  }, [preload, src]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      playRequestRef.current += 1;
      releaseActiveAudioPlayer(playerIdRef.current);
      releaseWarmedAudioPlayer(playerIdRef.current);
      const audio = audioRef.current;
      if (audio) {
        releaseNativeAudio(audio);
      }
    };
  }, []);

  useEffect(() => {
    const handleActivePlayerChange = (event: Event) => {
      if (!isActiveAudioEvent(event) || event.detail.id === playerIdRef.current) {
        return;
      }
      playRequestRef.current += 1;
      const audio = audioRef.current;
      if (audio) {
        releaseNativeAudio(audio);
      }
      setCurrentTime(0);
      setDuration(0);
      setHasError(false);
      setIsActive(false);
      setIsLoading(false);
      setIsPlaying(false);
    };

    const handleWarmupPlayerChange = (event: Event) => {
      if (!isActiveAudioEvent(event) || event.detail.id === playerIdRef.current) {
        return;
      }
      if (activeAudioPlayerId === playerIdRef.current) {
        return;
      }
      const audio = audioRef.current;
      if (audio) {
        releaseNativeAudio(audio);
      }
      setCurrentTime(0);
      setDuration(0);
      setHasError(false);
      setIsActive(false);
      setIsLoading(false);
      setIsPlaying(false);
    };

    window.addEventListener(AUDIO_PLAYER_ACTIVE_EVENT, handleActivePlayerChange);
    window.addEventListener(AUDIO_PLAYER_WARMUP_EVENT, handleWarmupPlayerChange);
    return () => {
      window.removeEventListener(AUDIO_PLAYER_ACTIVE_EVENT, handleActivePlayerChange);
      window.removeEventListener(AUDIO_PLAYER_WARMUP_EVENT, handleWarmupPlayerChange);
    };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.volume = volume;
    audio.muted = isMuted;
  }, [isMuted, volume]);

  const readDuration = useCallback(() => {
    const nextDuration = audioRef.current?.duration ?? 0;
    setDuration(Number.isFinite(nextDuration) ? nextDuration : 0);
  }, []);

  const handleCanPlay = useCallback(() => {
    setIsLoading(false);
    readDuration();
  }, [readDuration]);

  const handleError = useCallback(() => {
    if (!audioRef.current?.getAttribute("src")) {
      return;
    }
    releaseActiveAudioPlayer(playerIdRef.current);
    setHasError(true);
    setIsActive(false);
    setIsLoading(false);
    setIsPlaying(false);
  }, []);

  const handleTimeUpdate = useCallback(() => {
    const nextTime = audioRef.current?.currentTime ?? 0;
    setCurrentTime(Number.isFinite(nextTime) ? nextTime : 0);
  }, []);

  const handleEnded = useCallback(() => {
    releaseActiveAudioPlayer(playerIdRef.current);
    setIsActive(false);
    setIsPlaying(false);
    setCurrentTime(audioRef.current?.duration ?? 0);
  }, []);

  const warmupAudio = useCallback(
    (nextPreload: HTMLMediaElement["preload"] = "metadata") => {
      const audio = audioRef.current;
      if (!audio || !src || isActive || hasError) {
        return;
      }
      warmupAudioPlayer(playerIdRef.current);
      setNativeAudioSource(audio, src, nextPreload);
    },
    [hasError, isActive, src],
  );

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !src) {
      return;
    }
    if (isPlaying) {
      audio.pause();
      releaseActiveAudioPlayer(playerIdRef.current);
      releaseWarmedAudioPlayer(playerIdRef.current);
      setIsActive(false);
      return;
    }
    const requestId = playRequestRef.current + 1;
    playRequestRef.current = requestId;
    activateAudioPlayer(playerIdRef.current);
    setNativeAudioSource(audio, src, "auto");
    setIsActive(true);
    try {
      setHasError(false);
      setIsLoading(true);
      await audio.play();
      if (!mountedRef.current || requestId !== playRequestRef.current || activeAudioPlayerId !== playerIdRef.current) {
        audio.pause();
        return;
      }
      setIsPlaying(true);
    } catch {
      if (!mountedRef.current || requestId !== playRequestRef.current || activeAudioPlayerId !== playerIdRef.current) {
        return;
      }
      releaseActiveAudioPlayer(playerIdRef.current);
      releaseWarmedAudioPlayer(playerIdRef.current);
      setHasError(true);
      setIsActive(false);
      setIsPlaying(false);
    } finally {
      if (mountedRef.current && requestId === playRequestRef.current) {
        setIsLoading(false);
      }
    }
  }, [isPlaying, src]);

  const handleSeek = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const audio = audioRef.current;
      if (!audio || duration <= 0) {
        return;
      }
      const nextTime = (Number(event.target.value) / 100) * duration;
      audio.currentTime = nextTime;
      setCurrentTime(nextTime);
    },
    [duration],
  );

  const handleVolumeChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const nextVolume = Number(event.target.value) / 100;
    setVolume(nextVolume);
    setIsMuted(nextVolume === 0);
  }, []);

  const toggleMute = useCallback(() => {
    setIsMuted((current) => !current);
  }, []);

  const stateLabel = useMemo(() => {
    if (hasError) {
      return "--:--";
    }
    return formatTime(duration);
  }, [duration, hasError]);

  return (
    <div
      className={playerClassName}
      data-state={hasError ? "error" : isPlaying ? "playing" : "idle"}
      data-active={isActive}
      title={hasError ? label : undefined}
      onFocus={() => warmupAudio("metadata")}
      onPointerDownCapture={() => warmupAudio("auto")}
      onPointerEnter={() => warmupAudio("metadata")}
    >
      <audio
        className="audio-player__native"
        onCanPlay={handleCanPlay}
        onDurationChange={readDuration}
        onEnded={handleEnded}
        onError={handleError}
        onLoadedMetadata={readDuration}
        onPause={() => setIsPlaying(false)}
        onPlay={() => {
          activateAudioPlayer(playerIdRef.current);
          setIsActive(true);
          setIsLoading(false);
          setIsPlaying(true);
        }}
        onTimeUpdate={handleTimeUpdate}
        onWaiting={() => {
          if (activeAudioPlayerId === playerIdRef.current) {
            setIsLoading(true);
          }
        }}
        preload={preload}
        ref={audioRef}
      />
      <button
        aria-label={isPlaying ? `${label} pause` : `${label} play`}
        className="audio-player__button audio-player__button--main"
        disabled={!src}
        onClick={togglePlayback}
        type="button"
      >
        {isLoading ? (
          <LoaderCircle aria-hidden className="audio-player__spinner" />
        ) : isPlaying ? (
          <Pause aria-hidden className="audio-player__icon" />
        ) : (
          <Play aria-hidden className="audio-player__icon audio-player__icon--play" />
        )}
      </button>
      <div className="audio-player__body">
        <div className="audio-player__time-row">
          <span>{formatTime(currentTime)}</span>
          <span>{stateLabel}</span>
        </div>
        <input
          aria-label={`${label} progress`}
          className="audio-player__range"
          disabled={!duration || hasError}
          max="100"
          min="0"
          onChange={handleSeek}
          step="0.1"
          style={rangeStyle(progress)}
          type="range"
          value={Number.isFinite(progress) ? progress : 0}
        />
      </div>
      <div className="audio-player__volume">
        <button
          aria-label={isMuted ? `${label} unmute` : `${label} mute`}
          className="audio-player__button audio-player__button--volume"
          disabled={!src}
          onClick={toggleMute}
          type="button"
        >
          {isMuted || volume === 0 ? (
            <VolumeX aria-hidden className="audio-player__icon" />
          ) : (
            <Volume2 aria-hidden className="audio-player__icon" />
          )}
        </button>
        <input
          aria-label={`${label} volume`}
          className="audio-player__range audio-player__range--volume"
          max="100"
          min="0"
          onChange={handleVolumeChange}
          step="1"
          style={rangeStyle(volumePercent)}
          type="range"
          value={volumePercent}
        />
      </div>
    </div>
  );
}
