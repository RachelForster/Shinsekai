import { isTauriDesktop, saveDesktopHistoryExport } from "../../../shared/desktop/desktopApi";
import type { RecordingAudio } from "../audio/stageAudioMixer";

export interface HistoryShareMessage {
  speaker: string;
  body: string;
  user: boolean;
}

export type HistoryExportFormat = "png" | "mp4" | "webm";

export interface HistoryExportResult {
  name: string;
  path?: string;
  previewUrl?: string;
  format: HistoryExportFormat;
}

export async function saveHistoryExport(blob: Blob, format: HistoryExportFormat): Promise<HistoryExportResult> {
  if (isTauriDesktop()) {
    const { name, path, opened } = await saveDesktopHistoryExport(blob);
    return { name, path, format, previewUrl: opened ? undefined : URL.createObjectURL(blob) };
  }
  const name = `shinsekai-${new Date().toISOString().replace(/[:.]/g, "-")}.${format}`;
  const previewUrl = URL.createObjectURL(blob);
  // Use a separate URL so closing the preview cannot cancel a pending download.
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 30_000);
  return { name, previewUrl, format };
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number) {
  return text.split(/\r?\n/).flatMap((paragraph) => {
    const lines: string[] = [];
    let line = "";
    for (const word of paragraph.match(/[^\s\u3000-\u9fff]+|./gu) ?? []) {
      if (line && ctx.measureText(line + word).width > maxWidth) {
        lines.push(line.trimEnd());
        line = "";
      }
      for (const part of ctx.measureText(word).width > maxWidth ? word : [word]) {
        if (line && ctx.measureText(line + part).width > maxWidth) {
          lines.push(line.trimEnd());
          line = "";
        }
        if (line || part.trim()) line += part;
      }
    }
    lines.push(line);
    return lines;
  });
}

export async function renderHistoryScreenshot(messages: HistoryShareMessage[], title: string) {
  const width = 960;
  const margin = 50;
  const bubbleWidth = 735;
  const lineHeight = 34;
  const font = '"Segoe UI", "Microsoft YaHei", sans-serif';
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is unavailable");
  await document.fonts?.ready;
  ctx.font = `23px ${font}`;
  const layout = messages.map((message) => {
    const lines = wrapText(ctx, message.body, bubbleWidth - 44);
    return { ...message, lines, height: 68 + lines.length * lineHeight };
  });
  const height = 132 + layout.reduce((sum, message) => sum + message.height + 16, 0);
  // Guard against platform canvas limits before allocating the pixel buffer.
  if (height > 16_000) return null;
  canvas.width = width;
  canvas.height = height;
  ctx.fillStyle = "#151823";
  ctx.fillRect(0, 0, width, height);
  ctx.textBaseline = "top";
  ctx.fillStyle = "#f3edff";
  ctx.font = `bold 32px ${font}`;
  ctx.fillText(title, margin, 36, width - margin * 2);
  let y = 94;
  for (const { user, speaker, lines, height } of layout) {
    const x = user ? width - margin - bubbleWidth : margin;
    ctx.fillStyle = user ? "#30314c" : "#232839";
    ctx.beginPath();
    ctx.roundRect(x, y, bubbleWidth, height, 17);
    ctx.fill();
    ctx.fillStyle = user ? "#c7bbff" : "#a6d5ff";
    ctx.font = `bold 20px ${font}`;
    ctx.fillText(speaker, x + 22, y + 18, bubbleWidth - 44);
    ctx.fillStyle = "#f4f1fa";
    ctx.font = `23px ${font}`;
    lines.forEach((line, index) => ctx.fillText(line, x + 22, y + 49 + index * lineHeight));
    y += height + 16;
  }
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("PNG encoding failed"))), "image/png");
  });
}

type CaptureResult = { kind: "saved"; blob: Blob } | { kind: "cancelled" | "failed" };

export interface ReplayCapture {
  result: Promise<CaptureResult>;
  start: () => void;
  stop: (save: boolean) => void;
}

export function canCaptureReplay() {
  return (
    typeof navigator.mediaDevices?.getDisplayMedia === "function" &&
    typeof MediaRecorder !== "undefined" &&
    typeof AudioContext !== "undefined"
  );
}

export async function requestReplayCapture(recordAudio: () => RecordingAudio): Promise<ReplayCapture | null> {
  const options = {
    video: { displaySurface: "window", frameRate: { ideal: 30, max: 30 } },
    audio: false,
    monitorTypeSurfaces: "exclude",
    selfBrowserSurface: "include",
  };
  const audio = recordAudio();
  let display: MediaStream | undefined;
  const stopTracks = () => {
    display?.getTracks().forEach((track) => track.stop());
    audio.stop();
  };
  try {
    display = await navigator.mediaDevices.getDisplayMedia(options);
  } catch (error) {
    stopTracks();
    if (error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "AbortError")) {
      return null;
    }
    throw error;
  }
  const video = display.getVideoTracks()[0];
  let recorder: MediaRecorder;
  try {
    if (!video || video.getSettings().displaySurface === "monitor") throw new Error("A window or tab is required");
    await audio.ready;
    if (video.readyState === "ended" || audio.track.readyState === "ended") throw new Error("Capture has ended");
    const stream = new MediaStream([video, audio.track]);
    const mimeType = ["video/mp4", "video/webm"].find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  } catch (error) {
    stopTracks();
    throw error;
  }

  const chunks: Blob[] = [];
  let complete!: (result: CaptureResult) => void;
  const result = new Promise<CaptureResult>((resolve) => (complete = resolve));
  let outcome: "saved" | "cancelled" | "failed" = "failed";
  let started = false;
  let stopping = false;
  const finalize = () => {
    stopTracks();
    if (outcome === "saved" && chunks.length) {
      complete({ kind: "saved", blob: new Blob(chunks, { type: recorder.mimeType || chunks[0].type }) });
    } else {
      complete({ kind: outcome === "cancelled" ? "cancelled" : "failed" });
    }
  };
  const stop = (nextOutcome: typeof outcome) => {
    if (stopping) return;
    stopping = true;
    outcome = !started && nextOutcome === "saved" ? "cancelled" : nextOutcome;
    if (!started) finalize();
    else if (recorder.state !== "inactive") recorder.stop();
  };
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) chunks.push(event.data);
  });
  recorder.addEventListener("stop", finalize, { once: true });
  recorder.addEventListener("error", () => stop("failed"), { once: true });
  video.addEventListener("ended", () => stop("saved"), { once: true });
  audio.track.addEventListener("ended", () => stop("failed"), { once: true });

  return {
    result,
    start: () => {
      if (stopping) return;
      try {
        recorder.start(1000);
        started = true;
        outcome = "saved";
      } catch {
        stop("failed");
      }
    },
    stop: (save) => stop(save ? "saved" : "cancelled"),
  };
}
