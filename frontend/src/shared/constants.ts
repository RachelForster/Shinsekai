export const DEFAULT_CHARACTER_COLOR = "#d07d7d";
export const DEFAULT_SPRITE_GROUP = "默认";
export const TRANSPARENT_BACKGROUND_NAME = "透明场景";
export const LEGACY_TRANSPARENT_BACKGROUND_ALIAS = "透明背景";

export const LLM_PROVIDER_DOUBAO = "豆包";
export const LLM_PROVIDER_QWEN = "通义千问";
export const LLM_PROVIDER_SILICONFLOW = "硅基流动";

export const TAG_PREFIX_SPRITE = "立绘";
export const TAG_PREFIX_SCENE = "场景";
export const TAG_PREFIX_MUSIC = "音乐";
export const TAG_PREFIX_EFFECT = "特效";
export const TAG_PREFIX_IMAGE = "图片";
export const TAG_PREFIX_AMBIENT = "环境";

export const DEFAULT_SPRITE_TAGGING = "平静，站立";
export const LEGACY_UNSPECIFIED_LICENSE = "未标注";
export const LEGACY_TTS_NONE_LABEL = "不使用";
export const LEGACY_DEFAULT_USER_SPEAKER = "你";

export const DIALOG_SPEAKER_COT_ALIASES = ["COT", "思维链", "CG"] as const;
export const DIALOG_SPEAKER_OPTION_ALIASES = ["CHOICE", "OPTIONS", "选项"] as const;
export const DIALOG_SPEAKER_STAT_ALIASES = ["STAT", "STATS", "数值"] as const;
export const DIALOG_SPEAKER_SCENE_ALIASES = ["SCENE", "场景"] as const;
export const DIALOG_SPEAKER_NARRATION_ALIASES = ["NARR", "NARRATION", "旁白"] as const;

export const HIDDEN_HISTORY_SPEAKERS = ["scene", "场景", "bgm"] as const;
export const HIDDEN_HISTORY_LINE_PATTERN = /^\s*(?:scene|场景|bgm)\s*[：:]/i;
export const LOCAL_TIME_PREFIX_PATTERN = /^\[[^\]\n]*(?:本地时间|Local time)[^\]\n]*\]\s*/;

export const LANG_ALIAS_ENGLISH_ZH = "英语";
export const LANG_ALIAS_CHINESE_ZH = "中文";
