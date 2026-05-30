import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { FilePicker, NumberInput, TextInput } from "../../shared/ui";
import type { CharacterFieldChange } from "./characterEditorUtils";

interface CharacterVoiceSectionProps {
  draft: Character;
  onChange: CharacterFieldChange;
}

export function CharacterVoiceSection({ draft, onChange }: CharacterVoiceSectionProps) {
  const { t } = useI18n();

  return (
    <section className="section">
      <div className="section__header">
        <h2 className="section__title">{t("character.section.voice")}</h2>
      </div>
      <div className="form-grid form-grid--two">
        <label className="field-row">
          <span className="field-row__label">{t("character.field.gptModel")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".ckpt"]}
              onChange={(event) => onChange("gpt_model_path", event.target.value)}
              onPathChange={(path) => onChange("gpt_model_path", path)}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.field.gptModel")}
              readOnly={false}
              value={draft.gpt_model_path ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.sovitsModel")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".pth"]}
              onChange={(event) => onChange("sovits_model_path", event.target.value)}
              onPathChange={(path) => onChange("sovits_model_path", path)}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.field.sovitsModel")}
              readOnly={false}
              value={draft.sovits_model_path ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.referAudio")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
              onChange={(event) => onChange("refer_audio_path", event.target.value)}
              onPathChange={(path) => onChange("refer_audio_path", path)}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.field.referAudio")}
              readOnly={false}
              value={draft.refer_audio_path ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.promptLang")}</span>
          <span className="field-row__control">
            <TextInput
              onChange={(event) => onChange("prompt_lang", event.target.value)}
              value={draft.prompt_lang ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.promptText")}</span>
          <span className="field-row__control">
            <TextInput
              onChange={(event) => onChange("prompt_text", event.target.value)}
              value={draft.prompt_text ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.speechSpeed")}</span>
          <span className="field-row__control">
            <NumberInput
              max={5}
              min={0.1}
              onChange={(event) => onChange("speech_speed", Number(event.target.value))}
              step={0.05}
              value={draft.speech_speed}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.speechVolume")}</span>
          <span className="field-row__control">
            <NumberInput
              max={2}
              min={0}
              onChange={(event) => onChange("speech_volume", Number(event.target.value))}
              step={0.1}
              value={draft.speech_volume}
            />
          </span>
        </label>
      </div>
    </section>
  );
}
