import type { ChatThemePayload } from "../theme/chatChromeTheme";
import { builtinChatThemeManifests } from "../theme/builtinChatThemes";
import { DEFAULT_CHAT_THEME_ID, type ChatThemeSummary } from "../theme/chatTheme";
import { DEFAULT_CHARACTER_COLOR } from "../constants";
import type {
  AppConfig,
  ChatLaunchPayload,
  ChatSnapshot,
  McpConfig,
  McpToolPreview,
  PluginCatalogItem,
  PluginManifest,
  TemplateSummary,
} from "./types";

export const sampleConfig: AppConfig = {
  adapter_catalog: {
    asr: [
      {
        label: "Vosk",
        schema: {
          model_path: {
            default: "./assets/system/models/vosk-model-small-cn-0.22",
            label: "Vosk model path",
            type: "str",
          },
        },
        value: "vosk",
      },
      { label: "faster-whisper", schema: {}, value: "faster_whisper" },
      { label: "RealtimeSTT", schema: {}, value: "realtime_stt" },
    ],
    llm: [
      {
        label: "Deepseek",
        schema: {
          reasoning_effort: {
            choices: ["high", "max"],
            default: "high",
            label: "思考强度 (reasoning_effort)",
            type: "str",
          },
          thinking_enabled: {
            default: false,
            label: "思考模式",
            type: "bool",
          },
        },
        value: "Deepseek",
      },
      { label: "ChatGPT", schema: {}, value: "ChatGPT" },
      { label: "Gemini", schema: {}, value: "Gemini" },
      { label: "Claude", schema: {}, value: "Claude" },
      { label: "豆包", schema: {}, value: "豆包" },
      { label: "通义千问", schema: {}, value: "通义千问" },
    ],
    t2i: [
      { label: "ComfyUI", schema: {}, value: "comfyui" },
      { label: "Stable Diffusion", schema: {}, value: "stable diffusion" },
    ],
    tts: [
      { label: "不使用", schema: {}, value: "none" },
      { label: "Genie TTS", schema: {}, value: "genie-tts" },
      { label: "GPT SoVITS", schema: {}, value: "gpt-sovits" },
      { label: "IndexTTS", schema: {}, value: "index-tts" },
      { label: "CosyVoice", schema: {}, value: "cosyvoice" },
    ],
  },
  api_config: {
    gpt_sovits_api_path: "",
    gpt_sovits_url: "http://127.0.0.1:9880",
    tts_provider: "gpt-sovits",
    tts_speed: 1,
    tts_split_enabled: false,
    tts_max_sentence_length: 15,
    t2i_provider: "comfyui",
    t2i_work_path: "",
    t2i_api_url: "http://127.0.0.1:8188",
    t2i_default_workflow_path: "",
    t2i_prompt_node_id: "6",
    t2i_output_node_id: "9",
    llm_api_key: { Deepseek: "" },
    llm_base_url: "https://api.deepseek.com/v1",
    llm_model: {},
    llm_provider: "Deepseek",
    is_streaming: true,
    interrupt_enabled: true,
    is_batch_input_enabled: false,
    batch_input_timeout: 5,
    batch_input_separator: "\n---\n",
    temperature: 0.7,
    repetition_penalty: 1,
    presence_penalty: 0,
    frequency_penalty: 0,
    max_context_tokens: 128000,
    compact_threshold: 0.4,
    compact_target_ratio: 0.3,
    history_recent_messages: 20,
    max_tool_result_chars: 6000,
    max_active_tool_groups: 3,
    memory_auto_enabled: false,
    memory_extract_interval_turns: 5,
    memory_search_limit: 5,
    memory_recent_buffer_messages: 16,
    hugging_face_access_token: "",
    llm_extra_configs: {},
    tts_extra_configs: {},
    asr_extra_configs: {},
    t2i_extra_configs: {},
  },
  background_list: [
    {
      name: "默认房间",
      sprite_prefix: "room",
      sprites: [{ path: "/assets/system/picture/shinsekai.png" }],
      bg_tags: "室内、默认、夜晚",
      bgm_list: ["data/bgm/room/quiet-night.mp3"],
      bgm_tags: "音乐 1：安静、夜晚\n",
    },
  ],
  effect_list: [
    {
      name: "默认特效",
      color: "#5b8def",
      prompt_text: "通用场景音效",
      audio_list: [],
      audio_tags: "",
    },
  ],
  characters: [
    {
      name: "Nanami",
      color: DEFAULT_CHARACTER_COLOR,
      sprite_prefix: "nanami",
      sprites: [
        {
          path: "/assets/present_example.png",
          voice_path: "data/speech/nanami/hello.wav",
          voice_text: "欢迎来到新世界。",
        },
      ],
      character_setting: "温柔、带一点调皮的剧情向角色。",
      sprite_scale: 1,
      emotion_tags: "立绘 1：默认、微笑、惊讶\n",
      speech_speed: 1,
      speech_volume: 1,
      prompt_text: "欢迎来到新世界。",
      prompt_lang: "ja",
      pronunciation_map: { Nanami: "ななみ" },
    },
  ],
  system_config: {
    base_font_size_px: 56,
    ui_language: "zh_CN",
    voice_language: "ja",
    asr_provider: "vosk",
    asr_language: "",
    asr_whisper_model_size: "small",
    asr_whisper_device: "auto",
    asr_whisper_compute_type: "",
    music_volumn: 30,
    theme_color: "#d4788e",
    bgm_path: "",
    background_path: "",
    live_room_id: "",
    chat_window_geometry_b64: "",
    chat_ui_theme_path: "",
    chat_ui_theme_id: DEFAULT_CHAT_THEME_ID,
    chat_ui_runtime_mode: "react",
    react_chat_fork_experimental_enabled: false,
    react_chat_flowchart_experimental_enabled: false,
    mirror_auto_detect_china: true,
    mirror_region: "auto",
    huggingface_mirror_url: "",
    huggingface_cache_dir: "./data/cache/huggingface",
    github_mirror_url: "",
    pypi_mirror_url: "",
    network_proxy_enabled: false,
    http_proxy_url: "",
    https_proxy_url: "",
    socks5_proxy_url: "",
    music_cover_work_dir: "./data/music_cover",
    music_cover_yt_dlp_exe: "",
    music_cover_ffmpeg_exe: "",
    music_cover_uvr_cmd_template: "",
    music_cover_rvc_cmd_template: "",
    music_cover_rvc_model_path: "",
    music_cover_rvc_index_path: "",
    music_cover_rvc_device: "cuda:0",
    music_cover_rvc_model_version: "v2",
    music_cover_rvc_f0_method: "rmvpe",
    music_cover_rvc_pitch: 0,
    music_cover_rvc_index_rate: 0.75,
    music_cover_rvc_filter_radius: 3,
    music_cover_rvc_resample_sr: 0,
    music_cover_rvc_rms_mix_rate: 0.25,
    music_cover_rvc_protect: 0.33,
  },
};

export const sampleTemplates: TemplateSummary[] = [
  {
    id: "default",
    name: "默认叙事模板",
    path: "./data/character_templates/default.txt",
    updatedAt: "preview",
    content: "你正在和 {{characters}} 进行一场沉浸式对话。",
  },
];

export const samplePlugins: PluginManifest[] = [
  {
    author: "Shinsekai",
    id: "core-tools",
    directory: "plugins/core_tools",
    entry: "plugins.core_tools.plugin:CoreToolsPlugin",
    title: "内置工具",
    enabled: true,
    loaded: true,
    version: "built-in",
    description: "角色、记忆和文件工具。",
    permissions: ["tools"],
    settingsPages: [],
    slots: ["settings-tools"],
    toolsTabs: ["内置工具"],
  },
];

export const samplePluginCatalog: PluginCatalogItem[] = [
  {
    author: "Shinsekai",
    commitSha: "4aa82f9preview",
    displayName: "Vision Demo",
    downloadUrl: "https://r2.example.invalid/plugins/vision-demo/1.2.0/vision-demo.zip",
    description: "示例视觉理解插件，演示发现页、下载状态和安装进度。",
    downloaded: false,
    entry: "vision_demo.plugin:VisionDemoPlugin",
    forks: 2,
    id: "vision-demo",
    installed: false,
    name: "视觉理解示例",
    packageR2Key: "plugins/vision-demo/1.2.0/vision-demo.zip",
    packageSha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    packageSize: 524288,
    packageSource: "r2",
    packageUrl: "https://r2.example.invalid/plugins/vision-demo/1.2.0/vision-demo.zip",
    repo: "RachelForster/Shinsekai-Vision-Demo",
    securityScan: { bandit: { pass: true }, pip_audit: { pass: true } },
    sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    lowestShinsekaiVersion: ">=0.2.0",
    shortDescription: "Official R2 package preview with checksum metadata.",
    size: 524288,
    stars: 12,
    tags: ["vision", "demo", "official"],
    updatedAt: "2026-06-06T00:00:00Z",
    version: "1.2.0",
  },
  {
    author: "Community",
    description: "示例 ASR 适配器，浏览器预览不会访问真实网络。",
    downloaded: true,
    entry: "whisper_asr.plugin:WhisperAsrPlugin",
    installed: false,
    name: "Whisper ASR",
    repo: "RachelForster/Shinsekai-Whisper-ASR",
  },
];

export const sampleMcpConfig: McpConfig = {
  default_call_timeout: 300,
  enabled: true,
  path: "data/config/mcp.yaml",
  servers: [
    {
      enabled: true,
      name_prefix: "demo_",
      transport: "sse",
      url: "http://127.0.0.1:8765/sse",
    },
  ],
};

export const sampleMcpTools: McpToolPreview[] = [
  {
    description: "浏览器预览中的 MCP 工具。",
    name: "search",
    prefix: "demo_",
    registered_name: "demo_search",
  },
];

export const sampleChatSnapshot: ChatSnapshot = {
  backgroundPath: "",
  characterName: "Nanami",
  dialogText: "欢迎来到新世界。这里是 React 舞台预览，真实聊天事件会从 platform adapter 进入状态机。",
  experimentalFeatures: {
    conversationTree: true,
    forkHistory: true,
  },
  conversationTree: {
    activeBranchId: "main",
    branches: [{ id: "main", label: "Main", parentId: null }],
  },
  historyEntries: [
    { id: "history-0", role: "system", text: "旁白: 欢迎来到新世界。" },
    {
      createdAt: new Date(2026, 0, 2, 15, 4).getTime(),
      id: "history-1",
      revertUserIndex: 0,
      role: "user",
      text: "你: 你好，Nanami。",
    },
    { id: "history-2", role: "assistant", text: "Nanami: 欢迎来到新世界。" },
  ],
  historyPath: "./data/chat_history/preview",
  inputDraft: "",
  numericInfo: "idle",
  options: ["继续", "查看历史", "切换角色"],
  runtimeMode: "react",
  sprites: [{ id: "nanami-default", path: "/assets/present_example.png", label: "Nanami" }],
  stats: [
    { icon: "heart", label: "HP", max: 100, value: 72 },
    { icon: "sparkles", label: "Affinity", max: 100, value: 38 },
    { icon: "coins", label: "Gold", value: 320 },
  ],
  status: "idle",
  turnOptions: {
    batchEnabled: false,
    batchIdleSeconds: 5,
    interruptEnabled: true,
  },
  turnState: {
    enabled: false,
    pendingCount: 0,
    pendingMessages: [],
    remainingSeconds: null,
    scheduled: false,
    typing: false,
  },
  userDisplayName: "你",
  voiceLanguage: "ja",
};

export const sampleChatTheme: ChatThemePayload = {
  raw: {
    dialog_label: {
      extra_qss: "background-color: rgba(50,50,50,200); border-color: rgba(255,255,255,85); border-radius: 8px;",
    },
    dialog_offset_y: 0,
    dialog_padding: 32,
    dialog_width_pct: 86,
    option_row: {
      extra_qss: "background-color: rgba(50,50,50,175); border-color: rgba(255,255,255,70);",
      hover_extra_qss: "background-color: rgba(80,80,80,210);",
    },
    options_gap: 10,
  },
  themeColor: "rgba(50,50,50,200)",
};

export const sampleChatThemeManifests = builtinChatThemeManifests;

export const sampleChatThemeSummaries: ChatThemeSummary[] = Object.values(sampleChatThemeManifests).map((manifest) => ({
  id: manifest.id,
  name: manifest.name,
  author: manifest.author,
  version: manifest.version,
  source: "builtin",
}));

export const sampleLastLaunch: ChatLaunchPayload = {
  backgroundName: "默认房间",
  characters: ["Nanami"],
  historyPath: "",
  templateId: "default",
};
