import { useState } from "react";
import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { AlertDialog, Button, FilePicker, NumberInput, Select, TextInput } from "../../shared/ui";
import type { CharacterFieldChange } from "./characterEditorUtils";

interface CharacterVoiceSectionProps {
  draft: Character;
  id?: string;
  onChange: CharacterFieldChange;
  onRemoveProfile?: (profileId: string) => void;
  voiceReferenceReadOnly?: boolean;
  voiceProfilesEnabled?: boolean;
}

export function CharacterVoiceSection({
  draft: character,
  id,
  onChange: updateCharacter,
  onRemoveProfile,
  voiceReferenceReadOnly = false,
  voiceProfilesEnabled = false,
}: CharacterVoiceSectionProps) {
  const { t } = useI18n();
  const [selection, setSelection] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const profiles = character.voice_profiles ?? {};
  const profile = voiceProfilesEnabled ? profiles[selection] : undefined;
  const draft = profile ?? character;
  const showProfiles = voiceProfilesEnabled && !voiceReferenceReadOnly;
  const defaultName = character.default_voice_name?.trim();
  const defaultLabel = defaultName
    ? t("character.voice.namedDefaultProfile", { name: defaultName })
    : t("character.voice.defaultProfile");

  const firstProfile = Object.values(profiles)[0];
  const unnamed = t("character.voice.unnamedProfile");

  const addProfile = () => {
    const profileId = crypto.randomUUID();
    updateCharacter("voice_profiles", {
      ...profiles,
      [profileId]: {
        name: t("character.voice.numberedProfile", { number: Object.keys(profiles).length + 2 }),
        prompt_lang: character.prompt_lang,
        speech_speed: character.speech_speed ?? 1,
        speech_volume: character.speech_volume ?? 1,
      },
    });
    setSelection(profileId);
  };
  const onChange: CharacterFieldChange = (key, value) => {
    if (profile) {
      updateCharacter("voice_profiles", { ...profiles, [selection]: { ...profile, [key]: value } });
    } else {
      updateCharacter(key, value);
    }
  };

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.section.voice")}</h2>
      </div>
      {voiceReferenceReadOnly ? (
        <p className="character-voice-section__locked-note">{t("character.voice.kaggleLockedHint")}</p>
      ) : null}
      <div className="form-grid form-grid--two">
        {showProfiles && (
          <>
            <label className="field-row">
              <span className="field-row__label">{t("character.voice.profile")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("character.voice.profile")}
                  value={profile ? selection : ""}
                  onChange={(event) => setSelection(event.target.value)}
                >
                  <option value="">{defaultLabel}</option>
                  {Object.entries(profiles).map(([profileId, voice]) => (
                    <option key={profileId} value={profileId}>
                      {voice.name.trim() || t("character.voice.unnamedProfile")}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            <div className="inline-actions">
              <Button onClick={addProfile}>＋ {t("character.voice.addProfile")}</Button>
              {onRemoveProfile && (
                <Button disabled={!firstProfile} onClick={() => setConfirmRemove(true)} variant="danger">
                  {t("character.voice.removeProfile")}
                </Button>
              )}
            </div>
            <div className="form-grid form-grid--two field-row--full">
              <label className="field-row">
                <span className="field-row__label">{t("character.voice.profileName")}</span>
                <span className="field-row__control">
                  <TextInput
                    placeholder={profile ? t("character.voice.unnamedProfile") : t("character.voice.defaultProfile")}
                    value={profile ? profile.name : (character.default_voice_name ?? "")}
                    onChange={(event) => {
                      const name = event.target.value;
                      if (profile) {
                        updateCharacter("voice_profiles", { ...profiles, [selection]: { ...profile, name } });
                      } else {
                        updateCharacter("default_voice_name", name);
                      }
                    }}
                  />
                </span>
              </label>
            </div>
          </>
        )}
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
              disabled={voiceReferenceReadOnly}
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
              disabled={voiceReferenceReadOnly}
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
              disabled={voiceReferenceReadOnly}
              max={5}
              min={0.1}
              onChange={
                voiceReferenceReadOnly ? undefined : (event) => onChange("speech_speed", Number(event.target.value))
              }
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
      {confirmRemove && firstProfile && (
        <AlertDialog
          body={t("character.voice.removeProfileBody", {
            name: profile ? profile.name.trim() || unnamed : defaultName || defaultLabel,
            fallback: profile ? defaultName || defaultLabel : firstProfile.name.trim() || unnamed,
          })}
          cancelLabel={t("common.cancel")}
          closeLabel={t("common.close")}
          confirmLabel={t("common.delete")}
          onCancel={() => setConfirmRemove(false)}
          onConfirm={() => {
            onRemoveProfile?.(profile ? selection : "");
            setSelection("");
            setConfirmRemove(false);
          }}
          open
          title={t("character.voice.removeProfile")}
        />
      )}
    </section>
  );
}
