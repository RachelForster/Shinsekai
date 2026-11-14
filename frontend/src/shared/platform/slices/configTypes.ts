import type { Character, Mem0Status } from "./characterTypes";
import type { TaskProgressOptions, TaskSnapshot } from "./taskTypes";
import type { Background, Effect } from "./workspaceTypes";

export interface ApiConfig {
  gpt_sovits_api_path: string;
  gpt_sovits_url: string;
  tts_provider: string;
  tts_speed: number;
  tts_split_enabled: boolean;
  tts_max_sentence_length: number;
  t2i_provider: string;
  t2i_work_path: string;
  t2i_api_url: string;
  t2i_default_workflow_path: string;
  t2i_prompt_node_id: string;
  t2i_output_node_id: string;
  llm_api_key: Record<string, string>;
  llm_base_url: string;
  llm_base_urls: Record<string, string>;
  llm_model: Record<string, string>;
  llm_provider: string;
  is_streaming: boolean;
  vision_provider: string;
  vision_model: Record<string, string>;
  vision_config_version?: number;
  interrupt_enabled: boolean;
  is_batch_input_enabled: boolean;
  batch_input_timeout: number;
  batch_input_separator: string;
  temperature: number;
  repetition_penalty: number;
  presence_penalty: number;
  frequency_penalty: number;
  max_context_tokens: number;
  compact_threshold: number;
  compact_target_ratio: number;
  history_recent_messages: number;
  max_tool_result_chars: number;
  max_active_tool_groups: number;
  knowledge_enabled: boolean;
  knowledge_search_limit: number;
  memory_auto_enabled: boolean;
  memory_extract_interval_turns: number;
  memory_search_limit: number;
  memory_recent_buffer_messages: number;
  perception_enabled: boolean;
  perception_base_url: string;
  perception_api_key: string;
  perception_model: string;
  perception_use_gguf: boolean;
  perception_python_path: string;
  perception_interval_sec: number;
  perception_capture_interval_sec: number;
  perception_ocr_interval_sec: number;
  perception_frame_max_side: number;
  perception_diff_threshold: number;
  perception_ocr_enabled: boolean;
  perception_reflex_enabled: boolean;
  perception_reflex_cooldown_sec: number;
  perception_proactive_enabled: boolean;
  perception_salience_threshold: number;
  perception_proactive_cooldown_sec: number;
  hugging_face_access_token: string;
  llm_extra_configs: Record<string, Record<string, unknown>>;
  tts_extra_configs: Record<string, Record<string, unknown>>;
  asr_extra_configs: Record<string, Record<string, unknown>>;
  t2i_extra_configs: Record<string, Record<string, unknown>>;
  vision_extra_configs: Record<string, Record<string, unknown>>;
}

export interface SystemConfig {
  base_font_size_px: number;
  ui_language: string;
  voice_language: string;
  asr_provider: string;
  asr_language: string;
  asr_whisper_model_size: string;
  asr_whisper_device: string;
  asr_whisper_compute_type: string;
  music_volumn: number;
  theme_color: string;
  bgm_path: string;
  background_path: string;
  live_room_id: string;
  chat_window_geometry_b64: string;
  chat_ui_theme_path: string;
  chat_ui_theme_id: string;
  chat_ui_runtime_mode: "react";
  react_chat_fork_experimental_enabled: boolean;
  react_chat_flowchart_experimental_enabled: boolean;
  story_system_enabled: boolean;
  mirror_auto_detect_china: boolean;
  mirror_region: string;
  huggingface_mirror_url: string;
  huggingface_cache_dir: string;
  github_mirror_url: string;
  pypi_mirror_url: string;
  network_proxy_enabled: boolean;
  http_proxy_url: string;
  https_proxy_url: string;
  socks5_proxy_url: string;
  music_cover_work_dir: string;
  music_cover_yt_dlp_exe: string;
  music_cover_ffmpeg_exe: string;
  music_cover_uvr_cmd_template: string;
  music_cover_rvc_cmd_template: string;
  music_cover_rvc_model_path: string;
  music_cover_rvc_index_path: string;
  music_cover_rvc_device: string;
  music_cover_rvc_model_version: string;
  music_cover_rvc_f0_method: string;
  music_cover_rvc_pitch: number;
  music_cover_rvc_index_rate: number;
  music_cover_rvc_filter_radius: number;
  music_cover_rvc_resample_sr: number;
  music_cover_rvc_rms_mix_rate: number;
  music_cover_rvc_protect: number;
}

export interface NetworkProxyDetectionResult {
  http_proxy_url: string;
  https_proxy_url: string;
  socks5_proxy_url: string;
  source: string;
}

export interface AdapterExtraFieldSchema {
  choices?: string[];
  default?: unknown;
  label?: string;
  max?: number;
  min?: number;
  secret?: boolean;
  step?: number;
  type?: "bool" | "float" | "int" | "str" | string;
}

export interface AdapterOption {
  label: string;
  schema?: Record<string, AdapterExtraFieldSchema>;
  value: string;
}

export interface AdapterCatalog {
  asr: AdapterOption[];
  llm: AdapterOption[];
  t2i: AdapterOption[];
  tts: AdapterOption[];
  vision?: AdapterOption[];
}

export interface AppConfig {
  adapter_catalog?: AdapterCatalog;
  api_config: ApiConfig;
  background_list: Background[];
  characters: Character[];
  effect_list: Effect[];
  system_config: SystemConfig;
  tts_bundle_installed_paths?: Record<string, string>;
  vision_available?: boolean;
}

export interface LlmModelOption {
  id: string;
  tags: string[];
}

export interface LlmConnectionTestResult {
  message: string;
}

export interface ComfyUIConnectionTestResult {
  ok: boolean;
  code:
    | "connected"
    | "invalid_url"
    | "timeout"
    | "unreachable"
    | "auth_required"
    | "http_error"
    | "not_comfyui"
    | "tls_error";
  httpStatus?: number;
  serverVersion?: string;
}

export type TtsBundleKind = "genie" | "gptso" | "gptso50";

export interface TtsGpuInfo {
  device?: string;
  vendor?: string;
  vendor_id?: string;
  vram_gb?: number | string;
}

export interface TtsBundleRecommendation {
  gpus: TtsGpuInfo[];
  kind: TtsBundleKind;
  platform: string;
}

export interface TtsBundleDownloadResult {
  path: string;
  provider: "genie-tts" | "gpt-sovits";
}

export interface ModelAssetRef {
  assetId: string;
  /** Resolve the variant from persisted application config; mutually exclusive with variant. */
  configured?: boolean;
  variant?: string;
}

export interface ModelAssetStatus extends ModelAssetRef {
  cached: boolean;
  downloadable: boolean;
  path?: string;
  repoId?: string;
  source: "huggingface" | "local";
  title: string;
}

export interface ModelAssetDownloadResult extends ModelAssetStatus {
  downloaded: boolean;
}

export type MusicCoverSource = "youtube" | "bilibili" | "url";

export interface MusicCoverSearchResult {
  log: string;
}

export interface MusicCoverRunInput {
  pickIndex: number;
  query: string;
  skipRvc: boolean;
  source: MusicCoverSource;
}

export interface MusicCoverRunResult {
  audioPath: string;
  log: string;
}

export type MusicCoverConfigInput = Pick<
  SystemConfig,
  | "music_cover_ffmpeg_exe"
  | "music_cover_rvc_cmd_template"
  | "music_cover_rvc_device"
  | "music_cover_rvc_f0_method"
  | "music_cover_rvc_filter_radius"
  | "music_cover_rvc_index_path"
  | "music_cover_rvc_index_rate"
  | "music_cover_rvc_model_path"
  | "music_cover_rvc_model_version"
  | "music_cover_rvc_pitch"
  | "music_cover_rvc_protect"
  | "music_cover_rvc_resample_sr"
  | "music_cover_rvc_rms_mix_rate"
  | "music_cover_uvr_cmd_template"
  | "music_cover_work_dir"
  | "music_cover_yt_dlp_exe"
>;

export interface MusicCoverConfigResult {
  message: string;
  systemConfig: SystemConfig;
}

export interface ConfigPlatform {
  cancelTtsBundleDownload: (taskId: string) => Promise<TaskSnapshot<TtsBundleDownloadResult>>;
  downloadTtsBundle: (
    input: { kind: TtsBundleKind },
    options?: TaskProgressOptions<TtsBundleDownloadResult>,
  ) => Promise<TtsBundleDownloadResult>;
  fetchLlmModels: (input: { apiKey: string; baseUrl: string; provider: string }) => Promise<LlmModelOption[]>;
  testLlmConnection: (input: {
    apiKey: string;
    baseUrl: string;
    model: string;
    provider: string;
  }) => Promise<LlmConnectionTestResult>;
  testComfyuiConnection: (input: { baseUrl: string }) => Promise<ComfyUIConnectionTestResult>;
  get: () => Promise<AppConfig>;
  detectNetworkProxy: () => Promise<NetworkProxyDetectionResult>;
  getMemoryStatus: (options?: { startLoading?: boolean }) => Promise<Mem0Status>;
  getTtsBundleRecommendation: () => Promise<TtsBundleRecommendation>;
  saveApi: (config: ApiConfig) => Promise<ApiConfig>;
  saveSystem: (config: SystemConfig) => Promise<SystemConfig>;
}

export interface ModelAssetsPlatform {
  download: (
    input: ModelAssetRef,
    options?: TaskProgressOptions<ModelAssetDownloadResult>,
  ) => Promise<ModelAssetDownloadResult>;
  status: (input: ModelAssetRef) => Promise<ModelAssetStatus>;
}

export interface MusicCoverPlatform {
  run: (input: MusicCoverRunInput, options?: TaskProgressOptions<MusicCoverRunResult>) => Promise<MusicCoverRunResult>;
  saveConfig: (input: MusicCoverConfigInput) => Promise<MusicCoverConfigResult>;
  search: (input: { query: string; source: MusicCoverSource }) => Promise<MusicCoverSearchResult>;
}
