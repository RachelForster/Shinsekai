export interface PerceptionRawBufferStats {
  stateKeys: number;
  pendingEvents: number;
  hasFrame: boolean;
  dirty: boolean;
  game: string;
}

export interface PerceptionRpCacheStatus {
  currentDigest: string;
  recentDigestCount: number;
  unconsumedEventCount: number;
  totalNotableEvents: number;
  lastSalience: number;
  playerBusy: boolean;
  game: string;
  updatedAt: number;
}

export interface ScreenOcrRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type ScreenOcrScope = { mode: "bottom" | "full" } | { mode: "region"; region: ScreenOcrRegion };

export type ScreenPlaybackAudioState = "unavailable" | "playing" | "quiet" | "stopped";

export interface ScreenPlaybackAudioSettings {
  quietWindowMs: number;
  pauseSilenceMs: number;
  pauseStillMs: number;
  minPlaybackMs: number;
  silenceRms: number;
  quietRatio: number;
}

export interface PerceptionRuntimeState {
  enabled: boolean;
  active: boolean;
  screenShareActive: boolean;
  model: string;
  baseUrl: string;
  intervalSec: number;
  captureIntervalSec?: number;
  ocrIntervalSec?: number;
  frameMaxSide: number;
  diffThreshold: number;
  ocrEnabled?: boolean;
  screenPlaybackAudioSettings?: ScreenPlaybackAudioSettings;
  reflexEnabled: boolean;
  proactiveEnabled: boolean;
  salienceThreshold: number;
  lastError: string;
  rawBuffer?: PerceptionRawBufferStats;
  rpCache?: PerceptionRpCacheStatus;
}

export interface PerceptionEndpointOptions {
  apiKey?: string;
  baseUrl?: string;
  model?: string;
  pythonPath?: string;
}

export interface PerceptionSetupStatus {
  status: "ready" | "not_started" | "error" | "missing_dependency";
  downloadable?: boolean;
  message?: string;
  modelCached?: boolean;
  moduleName?: string;
  packageName?: string;
  pythonPath?: string;
}

export interface PerceptionHealthProbe {
  ok: boolean;
  baseUrl: string;
  configuredModel: string;
  modelPresent?: boolean;
  models: string[];
  error?: string;
  imageTest?: { ok: boolean; error?: string };
}

export interface PerceptionLocalServerStatus {
  state: "stopped" | "starting" | "running" | "external_running" | "failed";
  running: boolean;
  starting: boolean;
  managed: boolean;
  pid: number | null;
  pythonPath: string;
  detectedPythonPath: string;
  baseUrl: string;
  model: string;
  error: string;
  logs: string[];
}

export interface PerceptionLocalServerStartInput {
  baseUrl?: string;
  model?: string;
  pythonPath?: string;
  device?: string;
}

export interface PerceptionStatusResponse {
  chatSessionActive: boolean;
  config: {
    enabled: boolean;
    baseUrl: string;
    model: string;
    intervalSec: number;
    captureIntervalSec?: number;
    ocrIntervalSec?: number;
    frameMaxSide: number;
    diffThreshold: number;
    reflexEnabled: boolean;
    reflexCooldownSec: number;
    proactiveEnabled: boolean;
    salienceThreshold: number;
    proactiveCooldownSec: number;
  };
  ingestUrl: string;
  localServer?: PerceptionLocalServerStatus;
  runtime: PerceptionRuntimeState | null;
  setup?: PerceptionSetupStatus;
  health?: PerceptionHealthProbe;
}

export interface PerceptionIngestInput {
  capturedAtMs?: number;
  source?: string;
  game?: string;
  state?: Record<string, unknown>;
  replaceState?: boolean;
  event?: string | { type: string; data?: Record<string, unknown> };
  data?: Record<string, unknown>;
  events?: Array<{ type: string; data?: Record<string, unknown> }>;
  imageBase64?: string;
  mimeType?: string;
  ocrOnly?: boolean;
  ocrScope?: ScreenOcrScope;
  width?: number;
  height?: number;
  screenPlaybackAudio?: ScreenPlaybackAudioState;
  screenShareActive?: boolean;
}

export interface PerceptionIngestResult {
  ok: boolean;
  accepted: boolean;
  reason?: string;
  perception?: PerceptionRuntimeState | null;
}

export interface PerceptionPlatform {
  clear: () => Promise<{ ok: boolean; accepted: boolean; perception?: PerceptionRuntimeState | null }>;
  ingest: (input: PerceptionIngestInput) => Promise<PerceptionIngestResult>;
  startServer: (
    input?: PerceptionLocalServerStartInput,
  ) => Promise<{ ok: boolean; localServer: PerceptionLocalServerStatus }>;
  status: (options?: PerceptionEndpointOptions & { probe?: boolean }) => Promise<PerceptionStatusResponse>;
  stopServer: () => Promise<{ ok: boolean; localServer: PerceptionLocalServerStatus }>;
  testImage: (options: PerceptionEndpointOptions) => Promise<PerceptionHealthProbe>;
}
