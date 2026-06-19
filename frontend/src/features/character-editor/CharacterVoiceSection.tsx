import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { FilePicker, NumberInput, TextInput } from "../../shared/ui";
import type { CharacterFieldChange } from "./characterEditorUtils";

interface CharacterVoiceSectionProps {
  draft: Character;
  id?: string;
  onChange: CharacterFieldChange;
  voiceReferenceReadOnly?: boolean;
}

export function CharacterVoiceSection({
  draft,
  id,
  onChange,
  voiceReferenceReadOnly = false,
}: CharacterVoiceSectionProps) {
  const { t } = useI18n();

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.section.voice")}</h2>
      </div>
      <div className="form-grid form-grid--two">
        <label className="field-row">
          <span className="field-row__label">{t("character.field.gptModel")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".ckpt"]}
              disabled={voiceReferenceReadOnly}
              onChange={voiceReferenceReadOnly ? undefined : (event) => onChange("gpt_model_path", event.target.value)}
              onPathChange={voiceReferenceReadOnly ? undefined : (path) => onChange("gpt_model_path", path)}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.field.gptModel")}
              readOnly={voiceReferenceReadOnly}
              value={draft.gpt_model_path ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.sovitsModel")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".pth"]}
              disabled={voiceReferenceReadOnly}
              onChange={
                voiceReferenceReadOnly ? undefined : (event) => onChange("sovits_model_path", event.target.value)
              }
              onPathChange={voiceReferenceReadOnly ? undefined : (path) => onChange("sovits_model_path", path)}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.field.sovitsModel")}
              readOnly={voiceReferenceReadOnly}
              value={draft.sovits_model_path ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.referAudio")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
              disabled={voiceReferenceReadOnly}
              onChange={
                voiceReferenceReadOnly ? undefined : (event) => onChange("refer_audio_path", event.target.value)
              }
              onPathChange={voiceReferenceReadOnly ? undefined : (path) => onChange("refer_audio_path", path)}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.field.referAudio")}
              readOnly={voiceReferenceReadOnly}
              value={draft.refer_audio_path ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.promptLang")}</span>
          <span className="field-row__control">
            <TextInput
              onChange={voiceReferenceReadOnly ? undefined : (event) => onChange("prompt_lang", event.target.value)}
              readOnly={voiceReferenceReadOnly}
              value={draft.prompt_lang ?? ""}
            />
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.promptText")}</span>
          <span className="field-row__control">
            <TextInput
              onChange={voiceReferenceReadOnly ? undefined : (event) => onChange("prompt_text", event.target.value)}
              readOnly={voiceReferenceReadOnly}
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
