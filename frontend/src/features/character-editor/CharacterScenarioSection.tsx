import { HelpCircle, Languages, Plus, Save, Trash2 } from "lucide-react";

import type { Character, CharacterScenario } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, AudioPlayer, Button, EmptyState, FilePicker, TextInput } from "../../shared/ui";

export interface CharacterScenarioSectionProps {
  draft: Character;
  scenarioSavePending: boolean;
  scenarioVoiceUploadPending: boolean;
  translatePending: boolean;
  onAddScenario: () => void;
  onAiTranslate: () => void;
  onDeleteScenario: (index: number) => void;
  onSaveVoiceText: (index: number, text: string) => void;
  onScenarioNameChange: (index: number, name: string) => void;
  onScenarioVoiceTextChange: (index: number, text: string) => void;
  onScenarioVoiceTypeChange: (index: number, voiceType: string) => void;
  onSaveAllScenarios: () => void;
  onUploadScenarioVoice: (index: number, filePath: string) => void;
}

function Hint({ text }: { text: string }) {
  return (
    <span className="hint-icon" title={text}>
      <HelpCircle aria-hidden size={14} />
    </span>
  );
}

export function CharacterScenarioSection({
  draft,
  scenarioSavePending,
  scenarioVoiceUploadPending,
  translatePending,
  onAddScenario,
  onAiTranslate,
  onDeleteScenario,
  onSaveVoiceText,
  onScenarioNameChange,
  onScenarioVoiceTextChange,
  onScenarioVoiceTypeChange,
  onSaveAllScenarios,
  onUploadScenarioVoice,
}: CharacterScenarioSectionProps) {
  const { t } = useI18n();
  const scenarios: CharacterScenario[] = draft.scenarios ?? [];

  return (
    <section className="section">
      <div className="section__header">
        <h2 className="section__title">{t("character.section.voiceTags")}</h2>
        <div className="page__actions">
          <AsyncButton
            icon={<Languages aria-hidden className="button__icon" />}
            loading={translatePending}
            onClick={onAiTranslate}
            variant="ghost"
          >
            {t("character.voiceTag.aiTranslate")}
          </AsyncButton>
          <Button icon={<Plus aria-hidden className="button__icon" />} onClick={onAddScenario} variant="ghost">
            {t("character.voiceTag.add")}
          </Button>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={scenarioSavePending}
            onClick={onSaveAllScenarios}
            variant="ghost"
          >
            {t("character.voiceTag.saveAll")}
          </AsyncButton>
        </div>
      </div>

      <p className="section__description">{t("character.voiceTag.description")}</p>
      <p className="section__description">
        {t("character.voiceTag.voiceTypePreset")}：{t("character.voiceTag.voiceTypePresetHint")} &middot; {t("character.voiceTag.voiceTypeReference")}：{t("character.voiceTag.voiceTypeReferenceHint")} &middot; {t("character.voiceTag.saveBeforeTranslate")}
      </p>

      {scenarios.length === 0 && <EmptyState title={t("character.voiceTag.empty")} />}

      <div className="scenario-list">
        {scenarios.map((scenario, si) => {
          const voiceType = scenario.voice_type ?? "preset";
          const voicePath = scenario.voice_path ?? "";
          return (
            <div className="scenario-card" key={`scenario-${si}`}>
              <div className="scenario-card__row">
                <span className="scenario-card__index">{t("character.voiceTag.index", { index: si + 1 })}</span>
                <TextInput
                  className="scenario-card__name"
                  maxLength={15}
                  onChange={(event) => onScenarioNameChange(si, event.target.value)}
                  placeholder={t("character.voiceTag.namePlaceholder")}
                  value={scenario.name}
                />
                <span className="scenario-card__hint-group">
                  <Hint text={t("character.voiceTag.nameHint")} />
                  <FilePicker
                    acceptedExtensions={voiceType === "reference" ? [".wav"] : [".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
                    onPathChange={(path) => onUploadScenarioVoice(si, path)}
                    pickLabel={t("character.voiceTag.uploadVoice")}
                  />
                </span>
                {voicePath ? (
                  <>
                    <span className="scenario-card__filename">
                      {voicePath.split("/").pop()?.split("\\").pop()}
                    </span>
                    <AudioPlayer
                    className="scenario-card__player"
                    label={voicePath.split("/").pop()?.split("\\").pop() ?? "Audio"}
                    preload="metadata"
                    src={fileUrl(voicePath)}
                  />
                  </>
                ) : null}
                <div className="scenario-card__voice-type">
                  <label className="radio-group__item">
                    <input
                      checked={voiceType === "preset"}
                      className="radio-group__input"
                      name={`scenarioVoiceType-${si}`}
                      onChange={() => onScenarioVoiceTypeChange(si, "preset")}
                      type="radio"
                    />
                    <span>{t("character.voiceTag.voiceTypePreset")}</span>
                  </label>
                  <label className="radio-group__item">
                    <input
                      checked={voiceType === "reference"}
                      className="radio-group__input"
                      name={`scenarioVoiceType-${si}`}
                      onChange={() => onScenarioVoiceTypeChange(si, "reference")}
                      type="radio"
                    />
                    <span>{t("character.voiceTag.voiceTypeReference")}</span>
                  </label>
                  {voiceType === "reference" && (
                    <span className="scenario-card__hint">{t("character.voiceTag.voiceHint")}</span>
                  )}
                </div>
                <TextInput
                  className="scenario-card__voice-text"
                  onChange={(event) => onScenarioVoiceTextChange(si, event.target.value)}
                  placeholder={t("character.voiceTag.voiceText")}
                  value={scenario.voice_text ?? ""}
                />
                <div className="scenario-card__actions">
                  <Button
                    icon={<Trash2 aria-hidden className="button__icon" />}
                    onClick={() => onDeleteScenario(si)}
                    variant="ghost"
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
