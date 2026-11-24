import { translateRuntimeMessage } from "../../../../i18n/runtimeLanguage";
import type { AdapterCatalog, AdapterOption } from "../../../slices/configTypes";
import type { RuntimeTarget } from "../../../runtimeTarget";
import { claudeLlmAdapter } from "./llm/claudeAdapter";
import { openaiCompatibleLlmAdapter } from "./llm/openaiCompatibleAdapter";
import { LLM_PROVIDER_PRESETS } from "./llm/presets";
import { browserSpeechTtsAdapter } from "./tts/browserSpeechAdapter";
import { gptSovitsCloudAdapter } from "./tts/gptSovitsCloudAdapter";
import { minimaxTtsAdapter } from "./tts/minimaxTtsAdapter";
import { openaiSpeechTtsAdapter } from "./tts/openaiSpeechAdapter";
import { qwenTtsAdapter } from "./tts/qwenTtsAdapter";
import type { StandaloneLlmAdapter, StandaloneTtsAdapter } from "./types";

export const STANDALONE_LLM_ADAPTERS: StandaloneLlmAdapter[] = [claudeLlmAdapter, openaiCompatibleLlmAdapter];

export const STANDALONE_TTS_ADAPTERS: StandaloneTtsAdapter[] = [
  openaiSpeechTtsAdapter,
  minimaxTtsAdapter,
  qwenTtsAdapter,
  gptSovitsCloudAdapter,
  browserSpeechTtsAdapter,
];

export function resolveLlmAdapter(provider: string): StandaloneLlmAdapter {
  for (const adapter of STANDALONE_LLM_ADAPTERS) {
    if (adapter.supportsProvider(provider)) {
      return adapter;
    }
  }
  return openaiCompatibleLlmAdapter;
}

export function resolveTtsAdapter(ttsProvider: string): StandaloneTtsAdapter | null {
  const normalized = ttsProvider.trim();
  if (!normalized || normalized === "none") {
    return null;
  }
  return STANDALONE_TTS_ADAPTERS.find((item) => item.id === normalized) ?? null;
}

export function listRegisteredTtsAdapters(): StandaloneTtsAdapter[] {
  return [...STANDALONE_TTS_ADAPTERS];
}

export function buildStandaloneAdapterCatalog(target: RuntimeTarget): AdapterCatalog {
  const isToyBrowser = target === "toy" || target === "web";

  const ttsOptions: AdapterOption[] = [
    { value: "none", label: translateRuntimeMessage("plat.standalone.tts.noneLabel") },
    ...STANDALONE_TTS_ADAPTERS.map<AdapterOption>((adapter) => ({
      value: adapter.id,
      label:
        isToyBrowser && adapter.browserCors === "proxy-only"
          ? `${adapter.label} ${translateRuntimeMessage("plat.standalone.tts.corsSuffix")}`
          : adapter.label,
      schema: adapter.schema,
    })),
  ];

  const llmOptions: AdapterOption[] = Object.values(LLM_PROVIDER_PRESETS).map<AdapterOption>((preset) => ({
    value: preset.provider,
    label:
      isToyBrowser && preset.browserCors === "proxy-only"
        ? `${preset.label} ${translateRuntimeMessage("plat.standalone.llmProxySuffix")}`
        : preset.label,
  }));

  return {
    asr: [],
    llm: llmOptions,
    t2i: [],
    tts: ttsOptions,
    vision: [],
  };
}
