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

export type FieldKind =
  | "checkbox"
  | "color"
  | "file"
  | "integer"
  | "json"
  | "number"
  | "password"
  | "select"
  | "text"
  | "textarea"
  | "url";

export interface FormOption {
  label: string;
  value: string;
}

export interface FormFieldSchema<T extends object> {
  description?: string;
  label: string;
  max?: number;
  min?: number;
  name: keyof T;
  options?: FormOption[];
  pathKind?: "directory" | "file";
  placeholder?: string;
  required?: boolean;
  step?: number;
  type: FieldKind;
  visibleWhen?: (draft: T) => boolean;
}

export interface FormGroupSchema<T extends object> {
  description?: string;
  fields: Array<FormFieldSchema<T>>;
  id: string;
  title: string;
}
