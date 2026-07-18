import type { ChatThemePayload } from "../theme/chatChromeTheme";
import type { ChatThemeManifest, ChatThemeSummary, SaveChatThemeInput } from "../theme/chatTheme";

export interface Sprite {
  path: string;
  voice_path?: string;
  voice_text?: string;
  voice_type?: SpriteVoiceType;
}

export type SpriteVoiceType = "fallback" | "preset" | "reference";

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

export interface Effect {
  name: string;
  color: string;
  prompt_text: string;
  audio_list: string[];
  audio_tags: string;
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
  memory_auto_enabled: boolean;
  memory_extract_interval_turns: number;
  memory_search_limit: number;
  memory_recent_buffer_messages: number;
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
  chat_ui_theme_id: string;
  chat_ui_runtime_mode: string;
  react_chat_fork_experimental_enabled: boolean;
  react_chat_flowchart_experimental_enabled: boolean;
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

export interface AppConfig {
  adapter_catalog?: AdapterCatalog;
  api_config: ApiConfig;
  background_list: Background[];
  characters: Character[];
  effect_list: Effect[];
  system_config: SystemConfig;
  tts_bundle_installed_paths?: Record<string, string>;
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

export type PluginSlotId =
  | "chat-dialog-actions"
  | "chat-output"
  | "chat-toolbar"
  | "settings-extension"
  | "settings-tools";

export interface PluginManifest {
  author: string;
  description: string;
  directory?: string;
  enabled: boolean;
  entry: string;
  id: string;
  install?: PluginInstallMetadata;
  loadError?: string;
  loaded: boolean;
  permissions: string[];
  settingsPages: string[];
  slots: PluginSlotId[];
  title: string;
  toolsTabs: string[];
  version: string;
}

export interface PluginInstallMetadata {
  dependencyDetail?: string;
  dependencyStatus?: string;
  entry?: string;
  packageSha256?: string;
  packageSize?: number | null;
  packageSource?: string;
  packageStatus?: string;
  packageUrl?: string;
  refKind?: AppUpdateRefKind;
  repo?: string;
  sourceLabel?: string;
  sourceType?: string;
  tagName?: string;
}

export interface PluginCatalogItem {
  author: string;
  commitSha?: string;
  description: string;
  displayName?: string;
  downloadUrl?: string;
  downloaded: boolean;
  entry: string;
  forks?: number;
  id?: string;
  installed: boolean;
  logo?: string;
  name: string;
  packageR2Key?: string;
  packageSha256?: string;
  packageSize?: number | null;
  packageSource?: string;
  packageUrl?: string;
  readmeUrl?: string;
  repo: string;
  review?: Record<string, unknown>;
  securityScan?: Record<string, unknown>;
  sha256?: string;
  lowestShinsekaiVersion?: string;
  shortDescription?: string;
  size?: number | null;
  socialLink?: string;
  sourceUrl?: string;
  stars?: number;
  tags?: string[];
  trustLevel?: string;
  updatedAt?: string;
  verified?: boolean;
  version?: string;
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

export interface PluginSubmissionInput {
  author: string;
  desc: string;
  display_name: string;
  lowest_shinsekai_version?: string;
  repo: string;
  social_link?: string;
  tags: string[];
}

export interface PluginLocalScanResult extends PluginSubmissionInput {
  entry?: string;
  logo?: string;
  path: string;
  requirements?: string;
  shinsekai_version?: string;
  warnings: string[];
}

export interface PluginSubmissionPayload {
  json: string;
  submission: PluginSubmissionInput;
}

export interface PluginSubmissionValidationResult extends Partial<PluginSubmissionPayload> {
  errors: string[];
  ok: boolean;
}

export interface PluginSubmissionIssueResult extends PluginSubmissionPayload {
  issueUrl: string;
  submitUrl: string;
}

export interface PluginSubmissionClipboardResult extends PluginSubmissionPayload {
  clipboardText: string;
  message: string;
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
  effectNames?: string[];
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
  effectNames?: string[];
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
  effectNames: string[];
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

export interface SpritePromptResult {
  prompts: string[];
}

export interface SpriteGenerationResult {
  files: string[];
  message: string;
  outputDir: string;
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

export interface CharacterMemoryImportFilePreview {
  chunkCount: number;
  dialogueCharacters: number;
  dialogueLineCount: number;
  kind: string;
  name: string;
  sourceTokens: number;
}

export interface CharacterMemoryImportPreview {
  chunkCount: number;
  dialogueCharacters: number;
  dialogueLineCount: number;
  estimatedInputTokens: number;
  estimatedOutputTokens: number;
  estimatedTotalTokens: number;
  fileCount: number;
  files: CharacterMemoryImportFilePreview[];
  sourceTokens: number;
  warnings: string[];
}

export interface CharacterMemoryImportResult {
  chunkCount: number;
  duplicateCount: number;
  estimatedTotalTokens: number;
  extractedCount: number;
  fileCount: number;
  memories?: string[];
  savedCount: number;
}

export interface CharacterMemorySearchInput {
  limit?: number;
  name: string;
  query: string;
}

export interface Mem0Status {
  status: "ready" | "loading" | "not_started" | "error" | "missing_dependency";
  message?: string;
  modelCached?: boolean;
  moduleName?: string;
  packageName?: string;
  task?: TaskSnapshot;
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

export interface ChatRuntimeProcessState {
  chatProcessRunning: boolean;
  chatRuntimeClosing: boolean;
  state: "idle" | "running" | "closing";
}

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
  scale?: number;
  slot?: number;
  x?: number;
  y?: number;
}

export type ChatHistoryRole = "assistant" | "options" | "system" | "user";

export interface ChatHistoryEntry {
  createdAt?: number;
  id: string;
  revertUserIndex?: number;
  role: ChatHistoryRole;
  text: string;
}

export interface ChatConversationBranch {
  createdAt?: number;
  forkedFromEntryId?: string;
  forkedFromText?: string;
  id: string;
  label: string;
  parentId?: string | null;
  updatedAt?: number;
}

export interface ChatConversationTree {
  activeBranchId: string;
  branches: ChatConversationBranch[];
}

export interface ChatExperimentalFeatures {
  conversationTree: boolean;
  forkHistory: boolean;
}

export interface ChatTurnOptions {
  batchEnabled: boolean;
  batchIdleSeconds: number;
  interruptEnabled: boolean;
}

export interface ChatTurnState {
  enabled: boolean;
  pendingCount: number;
  pendingMessages?: string[];
  remainingSeconds: number | null;
  scheduled: boolean;
  typing: boolean;
}

export type ChatStatIcon = "clock" | "coins" | "gauge" | "heart" | "shield" | "sparkles" | "star" | "target" | "zap";

export interface ChatStat {
  icon: ChatStatIcon;
  label: string;
  max?: number;
  value: number;
}

export interface ChatSnapshot {
  backgroundPath?: string;
  bgmPath?: string;
  busyDurationSeconds?: number;
  busyText?: string;
  characterName?: string;
  conversationTree?: ChatConversationTree;
  cgPath?: string;
  chatProcessRunning?: boolean;
  chatRuntimeClosing?: boolean;
  dialogHtml?: string;
  dialogText: string;
  /** 后端已折叠进该 snapshot 的最新事件 seq，用于重连恢复幂等处理。 */
  eventSeq?: number;
  experimentalFeatures?: ChatExperimentalFeatures;
  historyEntries?: ChatHistoryEntry[];
  historyPath?: string;
  inputDraft: string;
  initTask?: TaskSnapshot;
  numericInfo?: string;
  notificationText?: string;
  options: string[];
  runtimeDependencyError?: RuntimeDependencyError;
  runtimeMode?: "native" | "react";
  sessionClosedReason?: string;
  sessionId?: string;
  sprites: ChatSprite[];
  stats?: ChatStat[];
  status: ChatRuntimeStatus;
  statusMessage?: string;
  systemMessageText?: string;
  turnOptions?: ChatTurnOptions;
  turnState?: ChatTurnState;
  userDisplayName?: string;
  voiceLanguage?: string;
  wsUrl?: string;
}

export interface ChatCommandResult extends ChatSnapshot {
  clipboardText?: string;
  downloadUrl?: string;
  openedPath?: string;
}

export type ChatTransportState = "connected" | "connecting" | "polling" | "reconnecting";
export type ChatTransportMode = "snapshot" | "websocket";

export interface ChatCommand {
  cmdId?: string;
  payload?: unknown;
  type:
    | "cancel-input-batch"
    | "change-voice-language"
    | "chat-input-state"
    | "clear-history"
    | "copy-history"
    | "dialog-advance"
    | "fork-history"
    | "flush-input-batch"
    | "open-history"
    | "pause-asr"
    | "rename-branch"
    | "revert-history"
    | "resume-asr"
    | "reroll"
    | "send-message"
    | "skip-speech"
    | "switch-branch"
    | "submit-option"
    | "update-turn-options";
}

export type ChatRealtimeCommandType = Exclude<ChatCommand["type"], "copy-history" | "open-history"> | "revert-history";

/** 上行命令（React→server，WebSocket），沿用并扩展 ChatCommand。 */
export interface ChatUpstreamCommand {
  /** 客户端生成，用于 ack 关联。 */
  cmdId: string;
  payload?: unknown;
  type: ChatRealtimeCommandType;
}

// --- chat stage 实时事件协议（下行 server→React，WebSocket）。详见设计文档"参考接口输出 · C"。 ---

interface ChatEventBase {
  v: 1;
  /** 单调递增，用于缺口检测 + 重连重放。 */
  seq: number;
  /** epoch 毫秒。 */
  ts: number;
}

export type ChatStageEvent =
  | (ChatEventBase & { type: "snapshot"; snapshot: ChatSnapshot })
  | (ChatEventBase & {
      type: "chat.init.progress" | "chat.init.completed" | "chat.init.failed" | "chat.init.cancelled";
      task: TaskSnapshot;
    })
  | (ChatEventBase & { type: "transport.state"; state: ChatTransportState; transport: ChatTransportMode })
  | (ChatEventBase & {
      type: "cmd.ack";
      cmdId: string;
      commandType: ChatRealtimeCommandType;
      error?: string;
      ok: boolean;
    })
  | (ChatEventBase & { type: "dialog.end"; speaker: string; color: string; isSystem: boolean; fullHtml: string })
  | (ChatEventBase & { type: "user.display_name.change"; name: string })
  | (ChatEventBase & { type: "history.replace"; entries: ChatHistoryEntry[] })
  | (ChatEventBase & { type: "conversation.tree"; tree: ChatConversationTree })
  | (ChatEventBase & { type: "chat.turn.state"; state: ChatTurnState })
  | (ChatEventBase & {
      type: "sprite.show";
      characterName: string;
      url: string;
      scale: number;
      slot?: number;
      x?: number;
      y?: number;
    })
  | (ChatEventBase & { type: "sprite.remove"; characterName: string })
  | (ChatEventBase & { type: "background.change"; url: string })
  | (ChatEventBase & { type: "bgm.change"; url: string })
  | (ChatEventBase & { type: "cg.show"; url: string })
  | (ChatEventBase & { type: "cg.hide" })
  | (ChatEventBase & { type: "options.show"; options: string[] })
  | (ChatEventBase & { type: "options.clear" })
  | (ChatEventBase & { type: "numeric.update"; html: string })
  | (ChatEventBase & { type: "stats.update"; stats: ChatStat[] })
  | (ChatEventBase & { type: "busy.show"; text: string; durationSeconds: number })
  | (ChatEventBase & { type: "busy.hide" })
  | (ChatEventBase & { type: "notification.change"; text: string })
  | (ChatEventBase & { type: "status.change"; status: ChatRuntimeStatus })
  | (ChatEventBase & { type: "tts.play"; url: string; characterName: string })
  | (ChatEventBase & { type: "tts.skip" })
  | (ChatEventBase & { type: "asr.partial"; text: string })
  | (ChatEventBase & { type: "asr.final"; text: string })
  | (ChatEventBase & { type: "asr.state"; running: boolean })
  | (ChatEventBase & { type: "reply.finished" })
  | (ChatEventBase & { type: "session.closed"; reason: string });

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
  completedItems?: number;
  createdAt: number;
  dependencyInstallStatus?: string;
  error?: string;
  errorCode?: string;
  errorDetail?: string;
  errorUserMessage?: string;
  fallbackAllowed?: boolean;
  httpStatus?: number;
  id: string;
  installSource?: string;
  installSourceLabel?: string;
  kind: string;
  logs: string[];
  message: string;
  notice?: string;
  noticeKind?: "error" | "info" | "warning";
  packageSha256?: string;
  packageSource?: string;
  packageStatus?: string;
  packageUrl?: string;
  phase: string;
  progress?: number | null;
  result?: TResult | null;
  status: TaskStatus;
  title: string;
  totalItems?: number;
  updatedAt: number;
}

export interface TaskProgressOptions<TResult = unknown> {
  onTaskUpdate?: (task: TaskSnapshot<TResult>) => void;
}

export interface ImageAutoLabelFailure {
  index: number;
  message: string;
}

export interface ImageAutoLabelResult {
  annotatedCount: number;
  failedCount: number;
  failures: ImageAutoLabelFailure[];
  name: string;
  scope: "background" | "character";
  skippedCount: number;
  tags: string;
  totalCount: number;
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

export interface ShinsekaiPlatform {
  backgrounds: {
    autoLabelImages: (
      name: string,
      options?: TaskProgressOptions<ImageAutoLabelResult>,
    ) => Promise<ImageAutoLabelResult>;
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
  effects: {
    delete: (name: string) => Promise<void>;
    deleteAllAudio: (name: string) => Promise<Effect>;
    deleteAudio: (name: string, index: number) => Promise<Effect>;
    export: (name: string) => Promise<string>;
    import: (items: File[] | string[]) => Promise<Effect[]>;
    list: () => Promise<Effect[]>;
    save: (effect: Effect, originalName?: string) => Promise<Effect>;
    saveAudioTags: (input: { audioTags: string; name: string }) => Promise<Effect>;
    uploadAudio: (input: { audioTags: string; name: string; paths: string[] }) => Promise<Effect>;
  };
  chat: {
    close: () => Promise<ChatSnapshot>;
    command: (command: ChatCommand) => Promise<ChatCommandResult>;
    getHistory: () => Promise<ChatHistoryEntry[]>;
    getRuntimeStatus: () => Promise<ChatRuntimeProcessState>;
    getSnapshot: () => Promise<ChatSnapshot>;
    getTheme: () => Promise<ChatThemePayload>;
    launch: (payload: ChatLaunchPayload, options?: TaskProgressOptions<ChatSnapshot>) => Promise<ChatSnapshot>;
    resumeLast: (options?: TaskProgressOptions<ChatSnapshot>) => Promise<ChatSnapshot>;
    subscribe: (listener: (snapshot: ChatSnapshot) => void) => () => void;
    // --- 主题 mod 系统 ---
    listThemes: () => Promise<ChatThemeSummary[]>;
    getThemeManifest: (id: string) => Promise<ChatThemeManifest>;
    getActiveThemeId: () => Promise<string>;
    setActiveThemeId: (id: string) => Promise<void>;
    /** 上传一个主题 .zip 安装（multipart）；返回安装后的概要。 */
    uploadTheme: (file: File) => Promise<ChatThemeSummary>;
    /** 创建或更新用户主题，同时保留主题目录中的资源文件。 */
    saveTheme: (input: SaveChatThemeInput) => Promise<ChatThemeSummary>;
    /** 删除一个用户主题。 */
    deleteTheme: (id: string) => Promise<void>;
    // --- 实时事件流（WebSocket）；M0 占位，M2/M3 接真实 WS ---
    subscribeEvents: (listener: (event: ChatStageEvent) => void) => () => void;
  };
  characters: {
    autoLabelSprites: (
      name: string,
      options?: TaskProgressOptions<ImageAutoLabelResult>,
    ) => Promise<ImageAutoLabelResult>;
    delete: (name: string) => Promise<void>;
    deleteMemory: (name: string, memoryId: string) => Promise<CharacterMemoryList>;
    deleteSpriteVoice: (name: string, spriteIndex: number) => Promise<Character>;
    export: (name: string) => Promise<string>;
    generateSetting: (input: { name: string; setting: string }) => Promise<CharacterSettingResult>;
    import: (items: File[] | string[]) => Promise<Character[]>;
    list: () => Promise<Character[]>;
    getMem0Status: () => Promise<Mem0Status>;
    importMemories: (
      name: string,
      items: File[],
      options?: TaskProgressOptions<CharacterMemoryImportResult>,
    ) => Promise<CharacterMemoryImportResult>;
    listMemories: (name: string) => Promise<CharacterMemoryList>;
    previewMemoryImport: (name: string, items: File[]) => Promise<CharacterMemoryImportPreview>;
    remember: (name: string, content: string) => Promise<CharacterMemoryList>;
    searchMemories: (input: CharacterMemorySearchInput) => Promise<CharacterMemoryList>;
    save: (character: Character, originalName?: string) => Promise<Character>;
    saveEmotionTags: (name: string, emotionTags: string) => Promise<Character>;
    saveSpriteScale: (name: string, scale: number) => Promise<Character>;
    saveSpriteVoiceText: (name: string, spriteIndex: number, voiceText: string) => Promise<Character>;
    saveSpriteVoiceType: (name: string, spriteIndex: number, voiceType: SpriteVoiceType) => Promise<Character>;
    deleteAllSprites: (name: string) => Promise<Character>;
    deleteSprite: (name: string, spriteIndex: number) => Promise<Character>;
    translateFields: (input: {
      characterSetting: string;
      emotionTags: string;
      name: string;
    }) => Promise<CharacterTranslateResult>;
    uploadSprites: (input: { emotionTags: string; name: string; paths: string[] }) => Promise<Character>;
    uploadSpriteVoice: (input: {
      name: string;
      spriteIndex: number;
      voicePath: string;
      voiceText: string;
      voiceType?: SpriteVoiceType;
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
    detectNetworkProxy: () => Promise<NetworkProxyDetectionResult>;
    getMemoryStatus: (options?: { startLoading?: boolean }) => Promise<Mem0Status>;
    getTtsBundleRecommendation: () => Promise<TtsBundleRecommendation>;
    saveApi: (config: ApiConfig) => Promise<ApiConfig>;
    saveSystem: (config: SystemConfig) => Promise<SystemConfig>;
  };
  modelAssets: {
    download: (
      input: ModelAssetRef,
      options?: TaskProgressOptions<ModelAssetDownloadResult>,
    ) => Promise<ModelAssetDownloadResult>;
    status: (input: ModelAssetRef) => Promise<ModelAssetStatus>;
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
    scanLocal: (input: { path: string }) => Promise<PluginLocalScanResult>;
    validateSubmission: (input: PluginSubmissionInput) => Promise<PluginSubmissionValidationResult>;
    buildSubmissionIssueUrl: (input: PluginSubmissionInput) => Promise<PluginSubmissionIssueResult>;
    copySubmissionJson: (input: PluginSubmissionInput) => Promise<PluginSubmissionClipboardResult>;
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
      input: { characterName: string; count: number },
      options?: TaskProgressOptions<SpritePromptResult>,
    ) => Promise<SpritePromptResult>;
    generateSprites: (
      input: { characterName: string; outputDir?: string; prompts: string[]; referenceImage: string },
      options?: TaskProgressOptions<SpriteGenerationResult>,
    ) => Promise<SpriteGenerationResult>;
    removeSpriteBackground: (
      input: { inputDir: string; outputDir?: string },
      options?: TaskProgressOptions<BatchToolResult>,
    ) => Promise<BatchToolResult>;
  };
}
