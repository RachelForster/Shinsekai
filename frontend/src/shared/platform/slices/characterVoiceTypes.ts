export interface VoiceProfile {
  name: string;
  gpt_model_path?: string | null;
  sovits_model_path?: string | null;
  refer_audio_path?: string | null;
  prompt_text?: string;
  prompt_lang?: string;
  speech_speed: number;
  speech_volume: number;
}
