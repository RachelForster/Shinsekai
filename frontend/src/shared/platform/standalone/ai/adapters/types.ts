import type { AdapterExtraFieldSchema, ApiConfig, LlmModelOption } from "../../../slices/configTypes";
import type { StandaloneRawMessage } from "../../storage/sessionStore";
import type { StandaloneHttpClient } from "../httpClient";

export type BrowserCorsSupport = "supported" | "proxy-only";

export interface StandaloneLlmInput {
  provider: string;
  apiKey: string;
  baseUrl: string;
  model: string;
  messages: StandaloneRawMessage[];
  temperature?: number;
  presencePenalty?: number;
  frequencyPenalty?: number;
  repetitionPenalty?: number;
  maxTokens?: number;
  extraConfig?: Record<string, unknown>;
  signal?: AbortSignal;
}

export interface StandaloneLlmResult {
  content: string;
  usageTokens?: number;
  model?: string;
}

export interface StandaloneLlmAdapter {
  id: string;
  label: string;
  browserCors: BrowserCorsSupport;
  supportsProvider: (provider: string) => boolean;
  complete: (input: StandaloneLlmInput, http: StandaloneHttpClient) => Promise<StandaloneLlmResult>;
  fetchModels: (
    input: { provider: string; apiKey: string; baseUrl: string },
    http: StandaloneHttpClient,
  ) => Promise<LlmModelOption[]>;
  testConnection: (
    input: { provider: string; apiKey: string; baseUrl: string; model: string },
    http: StandaloneHttpClient,
  ) => Promise<{ message: string }>;
}

export interface StandaloneTtsInput {
  text: string;
  characterName: string;
  voiceLanguage?: string;
  speed?: number;
  volume?: number;
  referAudioBlob?: Blob;
  referAudioText?: string;
  referAudioLang?: string;
  apiConfig: ApiConfig;
  signal?: AbortSignal;
}

export interface StandaloneTtsAdapter {
  id: string;
  label: string;
  browserCors: BrowserCorsSupport;
  description: string;
  schema: Record<string, AdapterExtraFieldSchema>;
  synthesize: (
    input: StandaloneTtsInput,
    extraConfig: Record<string, unknown>,
    http: StandaloneHttpClient,
  ) => Promise<Blob | null>;
}
