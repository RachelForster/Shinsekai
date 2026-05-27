import type { ApiConfig, AppConfig, Background, Character, SystemConfig } from "../../entities/config/types";
import type {
  AppUpdateInfo,
  AppUpdateRefKind,
  AppUpdateResult,
  McpConfig,
  McpToolPreview,
  PluginConfigSaveResult,
  PluginCatalogItem,
  PluginInstallInput,
  PluginManifest,
  PluginUIDetail,
} from "../../entities/plugin/types";
import type { ChatThemePayload } from "../theme/chatChromeTheme";

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

export interface PluginUninstallResult {
  folderNote?: string;
  message: string;
}

export type TtsBundleKind = "genie" | "gptso" | "gptso50";

export interface TtsBundleDownloadResult {
  path: string;
  provider: "genie-tts" | "gpt-sovits";
}

export type ChatRuntimeStatus = "idle" | "listening" | "generating" | "streaming" | "speaking" | "paused" | "error";

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

export type TaskStatus = "queued" | "running" | "succeeded" | "failed";

export type PathPickerMode = "directory" | "file";

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
    uploadSprites: (input: { emotionTags: string; name: string; paths: string[] }) => Promise<Character>;
    uploadSpriteVoice: (input: {
      name: string;
      spriteIndex: number;
      voicePath: string;
      voiceText: string;
    }) => Promise<Character>;
  };
  config: {
    downloadTtsBundle: (
      input: { kind: TtsBundleKind },
      options?: TaskProgressOptions<TtsBundleDownloadResult>,
    ) => Promise<TtsBundleDownloadResult>;
    fetchLlmModels: (input: { apiKey: string; baseUrl: string; provider: string }) => Promise<LlmModelOption[]>;
    get: () => Promise<AppConfig>;
    saveApi: (config: ApiConfig) => Promise<ApiConfig>;
    saveSystem: (config: SystemConfig) => Promise<SystemConfig>;
  };
  files: {
    browse: (options?: { path?: string; showHidden?: boolean }) => Promise<FileBrowserSnapshot>;
    fileUrl: (path: string) => string;
    openExternal: (url: string) => Promise<void>;
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
