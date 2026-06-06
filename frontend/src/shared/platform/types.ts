import type { ChatThemePayload } from "../theme/chatChromeTheme";

export interface Sprite {
  path: string;
  voice_path?: string;
  voice_text?: string;
}

export interface Character {
  name: string;
  color: string;
  sprite_prefix: string;
  sprites: Sprite[];
  character_setting: string;
  sprite_scale: number;
  emotion_tags: string;
  gpt_model_path?: string;
  sovits_model_path?: string;
  refer_audio_path?: string;
  prompt_text?: string;
  prompt_lang?: string;
  speech_speed: number;
  speech_volume: number;
  pronunciation_map: Record<string, string>;
}

export interface Background {
  name: string;
  sprite_prefix: string;
  sprites: Sprite[];
  bg_tags: string;
  bgm_list: string[];
  bgm_tags: string;
}

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
  llm_model: Record<string, string>;
  llm_provider: string;
  is_streaming: boolean;
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
  hugging_face_access_token: string;
  llm_extra_configs: Record<string, Record<string, unknown>>;
  tts_extra_configs: Record<string, Record<string, unknown>>;
  asr_extra_configs: Record<string, Record<string, unknown>>;
  t2i_extra_configs: Record<string, Record<string, unknown>>;
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

export interface AppConfig {
  adapter_catalog?: AdapterCatalog;
  api_config: ApiConfig;
  background_list: Background[];
  characters: Character[];
  system_config: SystemConfig;
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
}

export type PluginSlotId = "chat-output" | "chat-toolbar" | "settings-extension" | "settings-tools";

export interface PluginManifest {
  author: string;
  description: string;
  directory?: string;
  enabled: boolean;
  entry: string;
  id: string;
  loadError?: string;
  loaded: boolean;
  permissions: string[];
  settingsPages: string[];
  slots: PluginSlotId[];
  title: string;
  toolsTabs: string[];
  version: string;
}

export interface PluginCatalogItem {
  author: string;
  description: string;
  downloaded: boolean;
  entry: string;
  installed: boolean;
  name: string;
  repo: string;
}

export type PluginUIPageKind = "settings" | "tools";

export type AppUpdateRefKind = "latest" | "head" | "tag";

export interface AppUpdateInfo {
  repo: string;
  version: string;
}

export interface AppUpdateResult {
  detail?: string;
  frontendDistUpdated?: boolean;
  message: string;
  pipCode?: string;
  version: string;
}

export interface PluginInstallInput {
  overwrite?: boolean;
  refKind?: AppUpdateRefKind;
  source: string;
  tagName?: string;
}

export type McpTransport = "sse" | "stdio" | "streamable_http";

export interface McpServerEntry {
  args?: string[];
  call_timeout?: number;
  command?: string;
  enabled: boolean;
  env?: Record<string, string>;
  group?: string;
  headers?: Record<string, string>;
  name_prefix: string;
  transport: McpTransport;
  url?: string;
}

export interface McpConfig {
  default_call_timeout: number;
  enabled: boolean;
  path?: string;
  servers: McpServerEntry[];
}

export interface McpToolPreview {
  description: string;
  name: string;
  prefix: string;
  registered_name: string;
}

export type PluginConfigFieldType =
  | "boolean"
  | "file"
  | "integer"
  | "json"
  | "number"
  | "password"
  | "select"
  | "text"
  | "textarea"
  | "url";

export interface PluginConfigOption {
  label: string;
  value: string;
}

export interface PluginConfigFieldSchema {
  defaultValue?: unknown;
  description?: string;
  key: string;
  label: string;
  max?: number;
  min?: number;
  options?: PluginConfigOption[];
  pathKind?: "directory" | "file";
  placeholder?: string;
  required?: boolean;
  span?: "full";
  step?: number;
  type: PluginConfigFieldType;
}

export interface PluginConfigGroupSchema {
  description?: string;
  fields: PluginConfigFieldSchema[];
  id: string;
  title: string;
}

export interface PluginConfigFieldI18n {
  description?: string;
  label?: string;
  options?: Record<string, string>;
  placeholder?: string;
}

export interface PluginConfigGroupI18n {
  description?: string;
  fields?: Record<string, PluginConfigFieldI18n>;
  title?: string;
}

export interface PluginConfigPageI18n {
  description?: string;
  groups?: Record<string, PluginConfigGroupI18n>;
  restartHint?: string;
  title?: string;
}

export type PluginConfigI18nMap = Record<string, PluginConfigPageI18n>;

export type PluginConfigActionVariant = "danger" | "ghost" | "primary";

export interface PluginConfigAction {
  confirm?: string;
  description?: string;
  id: string;
  label: string;
  order: number;
  variant: PluginConfigActionVariant;
}

export interface PluginUIPage {
  actions?: PluginConfigAction[];
  description?: string;
  frontendUrl?: string;
  i18n?: PluginConfigI18nMap;
  id: string;
  kind: PluginUIPageKind;
  order: number;
  pluginId: string;
  pluginVersion: string;
  restartHint?: string;
  schema?: PluginConfigGroupSchema[];
  title: string;
  unavailableReason?: string;
  values?: Record<string, unknown>;
}

export interface PluginUIDetail {
  pages: PluginUIPage[];
  plugin: PluginManifest;
}

export interface PluginConfigSaveResult {
  message: string;
  page: PluginUIPage;
  plugin: PluginManifest;
}

export interface PluginConfigActionResult {
  message: string;
  page: PluginUIPage;
  plugin: PluginManifest;
  result: Record<string, unknown>;
}

export interface TemplateSummary {
  content: string;
  generationMessage?: string;
  id: string;
  name: string;
  path: string;
  scenario?: string;
  system?: string;
  updatedAt: string;
}

export interface ChatLaunchPayload {
  backgroundName: string;
  characters: string[];
  historyPath: string;
  initSpritePath?: string;
  resetHistory?: boolean;
  roomId?: string;
  scenario?: string;
  system?: string;
  templateName?: string;
  templateId: string;
  useCg?: boolean;
}

export interface TemplateGenerateInput {
  backgroundName: string;
  characters: string[];
  maxDialogItems?: number;
  maxSpeechChars?: number;
  name: string;
  scenario?: string;
  useCg?: boolean;
  useChoice?: boolean;
  useCot?: boolean;
  useEffect?: boolean;
  useNarration?: boolean;
  useStat?: boolean;
  useTranslation?: boolean;
  voiceLanguage?: string;
}

export interface TemplateLaunchSession {
  background: string;
  filenameStub: string;
  historyPath: string;
  initSpritePath: string;
  maxDialogItems: number;
  maxSpeechChars: number;
  roomId: string;
  scenario: string;
  selectedCharacters: string[];
  system: string;
  templateFileDropdown: string;
  useCg: boolean;
  useChoice: boolean;
  useCot: boolean;
  useEffect: boolean;
  useNarration: boolean;
  useStat: boolean;
  useTranslation: boolean;
  voiceLanguage: string;
}

export interface SpritePromptItem {
  label: string;
  prompt: string;
}

export interface SpritePromptResult {
  items?: SpritePromptItem[];
  prompts: string[];
}

export interface SpriteGenerationResult {
  file?: string;
  files: string[];
  label?: string;
  message: string;
  outputDir: string;
  prompt?: string;
}

export interface BatchToolResult {
  message: string;
  outputDir: string;
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

export interface LogSnapshot {
  content: string;
  entries?: LogStructuredEntry[];
  modifiedAt?: number;
  name: string;
  path: string;
  size: number;
  truncated?: boolean;
}

export interface LogStructuredEntry {
  [key: string]: unknown;
  event?: string;
  level?: string;
  line?: number;
  logger?: string;
  message?: string;
  plugin_id?: string;
  session_id?: string;
  task_id?: string;
  timestamp?: string;
}

export interface LogFileInfo {
  app?: string;
  modifiedAt?: number;
  name: string;
  path: string;
  relativePath?: string;
  size: number;
}

export interface LogFileList {
  files: LogFileInfo[];
}

export interface DiagnosticBundleResult {
  downloadUrl: string;
  path: string;
}

export interface CharacterSettingResult {
  characterSetting: string;
  message: string;
}

export interface CharacterTranslateResult {
  characterSetting: string;
  emotionTags: string;
  error?: string;
  name: string;
}

export interface CharacterMemory {
  id: string;
  memory: string;
}

export interface CharacterMemoryList {
  agentId: string;
  count: number;
  memories: CharacterMemory[];
}

export interface BackgroundTranslateResult {
  bgTags: string;
  bgmRowTags?: string[];
  bgmTags: string;
  error?: string;
  name: string;
}

export interface BackgroundTranslateInput {
  bgTags: string;
  bgmRowTags?: string[];
  bgmTags: string;
  name: string;
}

export interface LlmModelOption {
  id: string;
  tags: string[];
}

export interface LlmConnectionTestResult {
  message: string;
}

export interface PluginUninstallResult {
  folderNote?: string;
  message: string;
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

export type ChatRuntimeStatus = "idle" | "listening" | "generating" | "streaming" | "speaking" | "paused" | "error";

export interface RuntimeDependencyError {
  kind?: "missing_dependency";
  logPath?: string;
  message: string;
  moduleName: string;
  packageName: string;
}

export interface RuntimeDependencyInstallInput {
  moduleName: string;
}

export interface RuntimeDependencyInstallResult {
  message: string;
  moduleName: string;
  packageName: string;
  pipCode?: number;
  pipOutput?: string;
}

export interface ChatSprite {
  id: string;
  label: string;
  path: string;
}

export interface ChatSnapshot {
  backgroundPath?: string;
  characterName?: string;
  dialogText: string;
  historyPath?: string;
  inputDraft: string;
  numericInfo?: string;
  options: string[];
  runtimeDependencyError?: RuntimeDependencyError;
  sprites: ChatSprite[];
  status: ChatRuntimeStatus;
}

export interface ChatCommandResult extends ChatSnapshot {
  clipboardText?: string;
  downloadUrl?: string;
  openedPath?: string;
}

export interface ChatCommand {
  payload?: unknown;
  type:
    | "clear-history"
    | "copy-history"
    | "open-history"
    | "pause-asr"
    | "reroll"
    | "send-message"
    | "skip-speech"
    | "submit-option";
}

export type TaskStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type PathPickerMode = "directory" | "file" | "path";

export interface FileBrowserEntry {
  kind: PathPickerMode;
  modifiedAt?: number;
  name: string;
  path: string;
  size?: number | null;
}

export interface FileBrowserRoot {
  label: string;
  path: string;
}

export interface FileBrowserSnapshot {
  cwd: string;
  entries: FileBrowserEntry[];
  parent?: string;
  roots: FileBrowserRoot[];
}

export interface TaskSnapshot<TResult = unknown> {
  cancelRequested?: boolean;
  createdAt: number;
  error?: string;
  id: string;
  kind: string;
  logs: string[];
  message: string;
  phase: string;
  progress?: number | null;
  result?: TResult | null;
  status: TaskStatus;
  title: string;
  updatedAt: number;
}

export interface TaskProgressOptions<TResult = unknown> {
  onTaskUpdate?: (task: TaskSnapshot<TResult>) => void;
}

export interface ShinsekaiPlatform {
  backgrounds: {
    delete: (name: string) => Promise<void>;
    deleteAllBgm: (name: string) => Promise<Background>;
    deleteAllImages: (name: string) => Promise<Background>;
    deleteBgm: (name: string, index: number) => Promise<Background>;
    deleteImage: (name: string, index: number) => Promise<Background>;
    export: (name: string) => Promise<string>;
    import: (items: File[] | string[]) => Promise<Background[]>;
    list: () => Promise<Background[]>;
    save: (background: Background, originalName?: string) => Promise<Background>;
    saveBgmTags: (input: { bgmTags: string; name: string }) => Promise<Background>;
    saveImageTags: (input: { bgTags: string; name: string }) => Promise<Background>;
    translateFields: (input: BackgroundTranslateInput) => Promise<BackgroundTranslateResult>;
    uploadBgm: (input: { bgmTags: string; name: string; paths: string[] }) => Promise<Background>;
    uploadImages: (input: { bgTags: string; name: string; paths: string[] }) => Promise<Background>;
  };
  chat: {
    command: (command: ChatCommand) => Promise<ChatCommandResult>;
    getSnapshot: () => Promise<ChatSnapshot>;
    getTheme: () => Promise<ChatThemePayload>;
    launch: (payload: ChatLaunchPayload) => Promise<ChatSnapshot>;
    resumeLast: () => Promise<ChatSnapshot>;
    subscribe: (listener: (snapshot: ChatSnapshot) => void) => () => void;
  };
  characters: {
    delete: (name: string) => Promise<void>;
    deleteMemory: (name: string, memoryId: string) => Promise<CharacterMemoryList>;
    deleteSpriteVoice: (name: string, spriteIndex: number) => Promise<Character>;
    export: (name: string) => Promise<string>;
    generateSetting: (input: { name: string; setting: string }) => Promise<CharacterSettingResult>;
    import: (items: File[] | string[]) => Promise<Character[]>;
    list: () => Promise<Character[]>;
    listMemories: (name: string) => Promise<CharacterMemoryList>;
    remember: (name: string, content: string) => Promise<CharacterMemoryList>;
    save: (character: Character, originalName?: string) => Promise<Character>;
    saveEmotionTags: (name: string, emotionTags: string) => Promise<Character>;
    saveSpriteScale: (name: string, scale: number) => Promise<Character>;
    saveSpriteVoiceText: (name: string, spriteIndex: number, voiceText: string) => Promise<Character>;
    deleteAllSprites: (name: string) => Promise<Character>;
    deleteSprite: (name: string, spriteIndex: number) => Promise<Character>;
    translateFields: (input: {
      characterSetting: string;
      emotionTags: string;
      name: string;
    }) => Promise<CharacterTranslateResult>;
    registerSprites: (input: { items: { label: string; path: string }[]; name: string }) => Promise<Character>;
    uploadSprites: (input: { emotionTags: string; name: string; paths: string[] }) => Promise<Character>;
    uploadSpriteVoice: (input: {
      name: string;
      spriteIndex: number;
      voicePath: string;
      voiceText: string;
    }) => Promise<Character>;
  };
  config: {
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
    get: () => Promise<AppConfig>;
    getTtsBundleRecommendation: () => Promise<TtsBundleRecommendation>;
    saveApi: (config: ApiConfig) => Promise<ApiConfig>;
    saveSystem: (config: SystemConfig) => Promise<SystemConfig>;
  };
  files: {
    browse: (options?: { path?: string; showHidden?: boolean }) => Promise<FileBrowserSnapshot>;
    fileUrl: (path: string) => string;
    thumbnailBatch?: (
      paths: string[],
      options?: { delivery?: "data" | "url"; size?: number },
    ) => Promise<Record<string, string>>;
    thumbnailUrl: (path: string, options?: { size?: number }) => string;
    openExternal: (url: string) => Promise<void>;
  };
  logs: {
    exportDiagnostics: () => Promise<DiagnosticBundleResult>;
    getDefault: () => Promise<LogSnapshot>;
    import: (items: File[] | string[]) => Promise<LogSnapshot>;
    list: () => Promise<LogFileList>;
  };
  runtime: {
    installMissingDependency: (
      input: RuntimeDependencyInstallInput,
      options?: TaskProgressOptions<RuntimeDependencyInstallResult>,
    ) => Promise<RuntimeDependencyInstallResult>;
  };
  musicCover: {
    run: (
      input: MusicCoverRunInput,
      options?: TaskProgressOptions<MusicCoverRunResult>,
    ) => Promise<MusicCoverRunResult>;
    saveConfig: (input: MusicCoverConfigInput) => Promise<MusicCoverConfigResult>;
    search: (input: { query: string; source: MusicCoverSource }) => Promise<MusicCoverSearchResult>;
  };
  plugins: {
    appUpdateInfo: () => Promise<AppUpdateInfo>;
    appUpdateTags: () => Promise<string[]>;
    appUpdateRun: (
      input: { refKind: AppUpdateRefKind; tagName?: string },
      options?: TaskProgressOptions<AppUpdateResult>,
    ) => Promise<AppUpdateResult>;
    catalog: () => Promise<PluginCatalogItem[]>;
    install: (
      input: PluginInstallInput | string,
      options?: TaskProgressOptions<PluginManifest>,
    ) => Promise<PluginManifest>;
    getUi: (id: string) => Promise<PluginUIDetail>;
    list: () => Promise<PluginManifest[]>;
    repoTags: (repo: string) => Promise<string[]>;
    runUiAction: (
      id: string,
      pageId: string,
      actionId: string,
      values: Record<string, unknown>,
    ) => Promise<PluginConfigActionResult>;
    saveUiConfig: (id: string, pageId: string, values: Record<string, unknown>) => Promise<PluginConfigSaveResult>;
    setEnabled: (id: string, enabled: boolean) => Promise<PluginManifest>;
    uninstall: (id: string) => Promise<PluginUninstallResult>;
  };
  mcp: {
    getConfig: () => Promise<McpConfig>;
    openConfigFile: () => Promise<string>;
    previewTools: (config: McpConfig, options?: TaskProgressOptions<McpToolPreview[]>) => Promise<McpToolPreview[]>;
    saveAndApply: (config: McpConfig, options?: TaskProgressOptions<McpConfig>) => Promise<McpConfig>;
  };
  tasks: {
    get: <TResult = unknown>(id: string) => Promise<TaskSnapshot<TResult>>;
  };
  templates: {
    generate: (input: TemplateGenerateInput) => Promise<TemplateSummary>;
    getSession: () => Promise<TemplateLaunchSession | null>;
    list: () => Promise<TemplateSummary[]>;
    save: (template: TemplateSummary) => Promise<TemplateSummary>;
    saveSession: (session: TemplateLaunchSession) => Promise<TemplateLaunchSession>;
  };
  tools: {
    cropSprites: (
      input: { inputDir: string; outputDir?: string; ratio: number },
      options?: TaskProgressOptions<BatchToolResult>,
    ) => Promise<BatchToolResult>;
    generateSpritePrompts: (
      input: { characterName: string; count: number; language?: string },
      options?: TaskProgressOptions<SpritePromptResult>,
    ) => Promise<SpritePromptResult>;
    generateSprites: (
      input: { characterName: string; outputDir?: string; prompts: string[]; referenceImage: string },
      options?: TaskProgressOptions<SpriteGenerationResult>,
    ) => Promise<SpriteGenerationResult>;
    generateSpriteImage: (
      input: { characterName: string; label?: string; negativePrompt?: string; outputDir?: string; prompt: string },
      options?: TaskProgressOptions<SpriteGenerationResult>,
    ) => Promise<SpriteGenerationResult>;
    removeSpriteBackground: (
      input: { inputDir: string; outputDir?: string },
      options?: TaskProgressOptions<BatchToolResult>,
    ) => Promise<BatchToolResult>;
  };
}
