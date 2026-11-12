import { useCallback, useEffect, useRef, useState } from "react";

import { ingestPerception } from "../../../entities/perception/repository";
import type { ScreenOcrScope, ScreenPlaybackAudioState } from "../../../shared/platform/types";
import { createScreenPlaybackDetector, measureAudioLevel } from "./screenPlaybackAudio";

const DIFF_GRID_WIDTH = 64;
const DIFF_GRID_HEIGHT = 36;
const DIFF_REGION_WIDTH = 16;
const DIFF_REGION_HEIGHT = 12;
const JPEG_QUALITY = 0.76;
const MAX_UNCHANGED_FRAME_INTERVAL_MS = 12_000;
const OCR_FRAME_MAX_SIDE = 1280;
const BLACK_FRAME_NOTICE_MS = 8_000;

export interface UseScreenShareCaptureOptions {
  captureRequestSeq?: number;
  captureIntervalSec?: number;
  diffThreshold?: number;
  frameMaxSide?: number;
  ocrIntervalSec?: number;
  ocrEnabled?: boolean;
  proactiveEnabled?: boolean;
  characterAudioPlaying?: boolean;
  onBlackScreen?: () => void;
  onError?: (error: unknown, unsupported?: boolean) => void;
  onFrameError?: (error: unknown) => void;
  onStarted?: () => void;
  onStopped?: () => void;
  sessionClosed?: boolean;
}

function computeScaledDimensions(sourceWidth: number, sourceHeight: number, maxSide: number) {
  const safeMax = Math.min(1280, Math.max(256, Math.round(maxSide || 512)));
  const longest = Math.max(sourceWidth, sourceHeight);
  if (longest <= 0) {
    return { height: 288, width: 512 };
  }
  const scale = longest > safeMax ? safeMax / longest : 1;
  const width = Math.max(2, Math.round((sourceWidth * scale) / 2) * 2);
  const height = Math.max(2, Math.round((sourceHeight * scale) / 2) * 2);
  return { height, width };
}

function extractLumaGrid(ctx: CanvasRenderingContext2D): Uint8Array {
  const { data } = ctx.getImageData(0, 0, DIFF_GRID_WIDTH, DIFF_GRID_HEIGHT);
  const pixelCount = DIFF_GRID_WIDTH * DIFF_GRID_HEIGHT;
  const luma = new Uint8Array(pixelCount);
  for (let i = 0, p = 0; i < pixelCount; i += 1, p += 4) {
    // Integer Rec.601 luma approximation: (77*R + 150*G + 29*B) >> 8
    luma[i] = (77 * data[p]! + 150 * data[p + 1]! + 29 * data[p + 2]!) >> 8;
  }
  return luma;
}

function maxRegionLumaDiff(prev: Uint8Array, next: Uint8Array): number {
  let peak = 0;
  for (let top = 0; top < DIFF_GRID_HEIGHT; top += DIFF_REGION_HEIGHT) {
    for (let left = 0; left < DIFF_GRID_WIDTH; left += DIFF_REGION_WIDTH) {
      let sum = 0;
      for (let row = top; row < top + DIFF_REGION_HEIGHT; row += 1) {
        const start = row * DIFF_GRID_WIDTH + left;
        for (let index = start; index < start + DIFF_REGION_WIDTH; index += 1) {
          sum += Math.abs(next[index]! - prev[index]!);
        }
      }
      peak = Math.max(peak, sum);
    }
  }
  return peak / (DIFF_REGION_WIDTH * DIFF_REGION_HEIGHT * 255);
}

export function useScreenShareCapture({
  captureRequestSeq,
  captureIntervalSec = 0.5,
  diffThreshold = 0.035,
  frameMaxSide = 512,
  ocrEnabled = false,
  ocrIntervalSec = 1,
  proactiveEnabled = true,
  characterAudioPlaying = false,
  onBlackScreen,
  onError,
  onFrameError,
  onStarted,
  onStopped,
  sessionClosed = false,
}: UseScreenShareCaptureOptions) {
  const [sharing, setSharing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [ocrScope, setOcrScope] = useState<ScreenOcrScope>({ mode: "bottom" });
  const [playbackAudio, setPlaybackAudio] = useState<ScreenPlaybackAudioState>("unavailable");

  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const diffCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const uploadCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const lastFrameRef = useRef<{ luma: Uint8Array; sentAt: number } | null>(null);
  const lastMotionAtRef = useRef(0);
  const characterAudioPlayingRef = useRef(characterAudioPlaying);
  characterAudioPlayingRef.current = characterAudioPlaying;
  const blackFrameRef = useRef<{ since: number; reported: boolean } | null>(null);
  const pendingRequestRef = useRef<Promise<unknown> | null>(null);
  const frameErrorReportedRef = useRef(false);
  const timerRef = useRef<number>(0);
  const activeRef = useRef(false);
  const captureGenerationRef = useRef(0);
  const observedRequestSeqRef = useRef<number | undefined>(captureRequestSeq);

  const configRef = useRef({ diffThreshold, frameMaxSide, ocrEnabled, ocrScope });
  configRef.current = { diffThreshold, frameMaxSide, ocrEnabled, ocrScope };

  const callbacksRef = useRef({ onBlackScreen, onError, onFrameError, onStarted, onStopped });
  callbacksRef.current = { onBlackScreen, onError, onFrameError, onStarted, onStopped };

  const teardownLocalMedia = useCallback((notifyBackend: boolean, emitCallback: boolean) => {
    const wasActive = activeRef.current;
    activeRef.current = false;
    captureGenerationRef.current += 1;
    lastFrameRef.current = null;
    blackFrameRef.current = null;
    frameErrorReportedRef.current = false;
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = 0;
    }
    const stream = streamRef.current;
    streamRef.current = null;
    if (stream) {
      for (const track of stream.getTracks()) {
        track.onended = null;
        try {
          track.stop();
        } catch {
          // ignore track stop error
        }
      }
    }
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.srcObject = null;
      videoRef.current = null;
    }
    setSharing(false);
    setStarting(false);
    setPlaybackAudio("unavailable");
    if (wasActive && notifyBackend) {
      const pending = pendingRequestRef.current;
      const stopRequest = Promise.resolve(pending)
        .catch(() => {})
        .then(() => ingestPerception({ screenShareActive: false, source: "screen_share" }))
        .catch(() => {});
      pendingRequestRef.current = stopRequest;
      void stopRequest.then(() => {
        if (pendingRequestRef.current === stopRequest) {
          pendingRequestRef.current = null;
        }
      });
    }
    if (wasActive && emitCallback) {
      callbacksRef.current.onStopped?.();
    }
  }, []);

  const captureOnce = useCallback(async (force = false, ocrOnly = false) => {
    if (!activeRef.current || pendingRequestRef.current) {
      return;
    }
    const video = videoRef.current;
    if (!video || video.readyState < 2 || video.videoWidth <= 0 || video.videoHeight <= 0) {
      return;
    }

    const capturedAtMs = Date.now();
    const lastFrame = lastFrameRef.current;
    const { diffThreshold, frameMaxSide, ocrEnabled: captureForOcr } = configRef.current;
    let currentLuma: Uint8Array | null = null;
    if (ocrOnly) {
      if (!captureForOcr) {
        return;
      }
    } else {
      let diffCanvas = diffCanvasRef.current;
      if (!diffCanvas) {
        diffCanvas = document.createElement("canvas");
        diffCanvas.width = DIFF_GRID_WIDTH;
        diffCanvas.height = DIFF_GRID_HEIGHT;
        diffCanvasRef.current = diffCanvas;
      }
      const diffCtx = diffCanvas.getContext("2d", { willReadFrequently: true });
      if (!diffCtx) {
        return;
      }
      diffCtx.drawImage(video, 0, 0, DIFF_GRID_WIDTH, DIFF_GRID_HEIGHT);
      currentLuma = extractLumaGrid(diffCtx);
      const now = performance.now();
      if (currentLuma.every((pixel) => pixel <= 4)) {
        const blackFrame = blackFrameRef.current ?? { since: now, reported: false };
        blackFrameRef.current = blackFrame;
        if (!blackFrame.reported && now - blackFrame.since >= BLACK_FRAME_NOTICE_MS) {
          blackFrame.reported = true;
          callbacksRef.current.onBlackScreen?.();
        }
        return;
      }
      blackFrameRef.current = null;
      const threshold = Math.max(0, Math.min(0.5, Number(diffThreshold) || 0));
      const change = lastFrame ? maxRegionLumaDiff(lastFrame.luma, currentLuma) : 1;
      if (change >= Math.max(0.015, threshold)) lastMotionAtRef.current = now;
      if (!force && lastFrame && now - lastFrame.sentAt < MAX_UNCHANGED_FRAME_INTERVAL_MS && change < threshold) {
        return;
      }
    }
    const { width, height } = computeScaledDimensions(
      video.videoWidth,
      video.videoHeight,
      captureForOcr ? OCR_FRAME_MAX_SIDE : frameMaxSide,
    );
    let uploadCanvas = uploadCanvasRef.current;
    if (!uploadCanvas) {
      uploadCanvas = document.createElement("canvas");
      uploadCanvasRef.current = uploadCanvas;
    }
    if (uploadCanvas.width !== width || uploadCanvas.height !== height) {
      uploadCanvas.width = width;
      uploadCanvas.height = height;
    }
    const uploadCtx = uploadCanvas.getContext("2d");
    if (!uploadCtx) {
      return;
    }
    uploadCtx.drawImage(video, 0, 0, width, height);
    const dataUrl = uploadCanvas.toDataURL("image/jpeg", JPEG_QUALITY);
    const commaIdx = dataUrl.indexOf(",");
    const imageBase64 = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl;
    if (!imageBase64) {
      return;
    }

    const upload = ingestPerception({
      capturedAtMs,
      height,
      imageBase64,
      mimeType: "image/jpeg",
      ...(ocrOnly ? { ocrOnly: true } : {}),
      ...(captureForOcr ? { ocrScope: configRef.current.ocrScope } : {}),
      screenShareActive: true,
      source: "screen_share",
      width,
    });
    pendingRequestRef.current = upload;
    try {
      const result = await upload;
      if (!result.accepted) {
        throw new Error(result.reason);
      }
      if (videoRef.current === video) {
        if (currentLuma) {
          lastFrameRef.current = { luma: currentLuma, sentAt: performance.now() };
        }
        frameErrorReportedRef.current = false;
        if (!lastFrame && currentLuma) {
          callbacksRef.current.onStarted?.();
        }
      }
    } catch (error) {
      if (videoRef.current === video && !frameErrorReportedRef.current) {
        frameErrorReportedRef.current = true;
        callbacksRef.current.onFrameError?.(error);
      }
    } finally {
      if (pendingRequestRef.current === upload) {
        pendingRequestRef.current = null;
      }
    }
  }, []);

  const changeOcrScope = useCallback(
    (scope: ScreenOcrScope) => {
      configRef.current.ocrScope = scope;
      setOcrScope(scope);
      const generation = captureGenerationRef.current;
      void Promise.resolve(pendingRequestRef.current)
        .catch(() => {})
        .then(() => {
          if (generation === captureGenerationRef.current && configRef.current.ocrScope === scope) {
            void captureOnce(false, true);
          }
        });
    },
    [captureOnce],
  );

  const stopSharing = useCallback(() => {
    teardownLocalMedia(true, true);
  }, [teardownLocalMedia]);

  const startSharing = useCallback(async () => {
    if (activeRef.current || starting || sessionClosed) {
      return;
    }
    if (typeof navigator === "undefined" || typeof navigator.mediaDevices?.getDisplayMedia !== "function") {
      callbacksRef.current.onError?.(new Error("getDisplayMedia unavailable"), true);
      return;
    }
    const generation = ++captureGenerationRef.current;
    setStarting(true);
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        audio: proactiveEnabled,
        video: {
          frameRate: { ideal: 5, max: 5 },
        },
      });
      const videoTrack = stream.getVideoTracks()[0];
      if (generation !== captureGenerationRef.current || !videoTrack || videoTrack.readyState === "ended") {
        for (const track of stream.getTracks()) {
          track.stop();
        }
        if (generation !== captureGenerationRef.current) {
          return;
        }
        throw new Error("No live video track returned from screen share");
      }

      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;

      streamRef.current = stream;
      videoRef.current = video;
      lastMotionAtRef.current = performance.now();
      if (configRef.current.ocrScope.mode === "region") {
        const bottomScope: ScreenOcrScope = { mode: "bottom" };
        configRef.current.ocrScope = bottomScope;
        setOcrScope(bottomScope);
      }
      activeRef.current = true;
      setSharing(true);
      setStarting(false);

      videoTrack.onended = () => {
        teardownLocalMedia(true, true);
      };

      await video.play();
      if (videoRef.current === video) {
        void captureOnce();
      }
    } catch (error) {
      if (generation !== captureGenerationRef.current) {
        return;
      }
      teardownLocalMedia(true, false);
      const errName = error instanceof DOMException ? error.name : (error as { name?: string } | null)?.name;
      if (errName !== "AbortError") {
        callbacksRef.current.onError?.(error, false);
      }
    }
  }, [captureOnce, proactiveEnabled, sessionClosed, starting, teardownLocalMedia]);

  const toggleSharing = useCallback(() => {
    if (activeRef.current) {
      stopSharing();
    } else {
      void startSharing();
    }
  }, [startSharing, stopSharing]);

  useEffect(() => {
    if (!sharing) {
      return;
    }
    const intervalMs = Math.max(200, Math.min(5_000, Math.round((Number(captureIntervalSec) || 0.5) * 1000)));
    const id = window.setInterval(() => {
      void captureOnce(false);
    }, intervalMs);
    timerRef.current = id;
    return () => {
      window.clearInterval(id);
      if (timerRef.current === id) {
        timerRef.current = 0;
      }
    };
  }, [captureIntervalSec, captureOnce, sharing]);

  useEffect(() => {
    if (!sharing || !ocrEnabled) {
      return;
    }
    const intervalMs = Math.max(500, Math.min(10_000, Math.round((Number(ocrIntervalSec) || 1) * 1000)));
    const id = window.setInterval(() => void captureOnce(false, true), intervalMs);
    return () => window.clearInterval(id);
  }, [captureOnce, ocrEnabled, ocrIntervalSec, sharing]);

  useEffect(() => {
    const stream = streamRef.current;
    const track = stream?.getAudioTracks()[0];
    if (!sharing || !proactiveEnabled || !stream || !track || typeof AudioContext === "undefined") return;

    let audio: AudioContext | undefined;
    let source: MediaStreamAudioSourceNode;
    let analyser: AnalyserNode;
    try {
      audio = new AudioContext();
      source = audio.createMediaStreamSource(stream);
      analyser = audio.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
    } catch {
      void audio?.close().catch(() => {});
      return;
    }
    const audioContext = audio;
    const resumeAudio = () => {
      if (audioContext.state === "suspended") void audioContext.resume().catch(() => {});
    };
    resumeAudio();
    window.addEventListener("pointerdown", resumeAudio);

    const samples = new Float32Array(analyser.fftSize);
    const detectPlayback = createScreenPlaybackDetector();
    let sentState: ScreenPlaybackAudioState | undefined;
    let shownState: ScreenPlaybackAudioState = "unavailable";
    let sentAt = 0;
    const timer = window.setInterval(() => {
      if (!activeRef.current || streamRef.current !== stream) return;
      const now = performance.now();
      const available = audioContext.state === "running" && track.readyState === "live" && !track.muted;
      const level = available && !characterAudioPlayingRef.current ? measureAudioLevel(analyser, samples) : null;
      const state = detectPlayback(level, now, lastMotionAtRef.current);
      const status = available ? (state === "unavailable" ? "playing" : state) : "unavailable";
      if (shownState !== status) {
        shownState = status;
        setPlaybackAudio(status);
      }
      if (pendingRequestRef.current || (state === sentState && now - sentAt < 800)) return;

      const request = ingestPerception({
        capturedAtMs: Date.now(),
        screenPlaybackAudio: state,
        screenShareActive: true,
        source: "screen_share",
      });
      pendingRequestRef.current = request;
      sentAt = now;
      sentState = state;
      void request
        .catch(() => {})
        .finally(() => {
          if (pendingRequestRef.current === request) pendingRequestRef.current = null;
        });
    }, 120);

    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pointerdown", resumeAudio);
      source.disconnect();
      void audioContext.close().catch(() => {});
      setPlaybackAudio("unavailable");
    };
  }, [proactiveEnabled, sharing]);

  useEffect(() => {
    if (sharing && captureRequestSeq != null && captureRequestSeq !== observedRequestSeqRef.current) {
      observedRequestSeqRef.current = captureRequestSeq;
      void captureOnce(true);
    } else {
      observedRequestSeqRef.current = captureRequestSeq;
    }
  }, [captureOnce, captureRequestSeq, sharing]);

  useEffect(() => {
    if (sessionClosed) {
      teardownLocalMedia(false, false);
    }
  }, [sessionClosed, teardownLocalMedia]);

  useEffect(
    () => () => {
      teardownLocalMedia(true, false);
    },
    [teardownLocalMedia],
  );

  return {
    changeOcrScope,
    ocrScope,
    playbackAudio,
    sharing,
    stream: sharing ? streamRef.current : null,
    startSharing,
    starting,
    stopSharing,
    toggleSharing,
  };
}
