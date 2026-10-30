import { Film } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { CharacterSpriteAnimationInput } from "../../shared/platform/types";
import {
  AsyncButton,
  FilePicker,
  ImageAssetThumb,
  SegmentedTabs,
  Select,
  Switch,
  TextArea,
  TextInput,
} from "../../shared/ui";
import type { SpriteAnimationSource } from "./spriteAnimationSources";

interface Props {
  value: CharacterSpriteAnimationInput;
  sources: SpriteAnimationSource[];
  selectedSources: string[];
  sourceMode: "library" | "file";
  onSourceModeChange: (mode: "library" | "file") => void;
  onChange: (value: CharacterSpriteAnimationInput) => void;
  onGenerate: () => void;
  busy: boolean;
  loading: boolean;
  remaining: number;
  hasItems: boolean;
}

export function SpriteAnimationSettings({
  value,
  sources,
  selectedSources,
  sourceMode,
  onSourceModeChange,
  onChange,
  onGenerate,
  busy,
  loading,
  remaining,
  hasItems,
}: Props) {
  const { t } = useI18n();
  const patch = (next: Partial<CharacterSpriteAnimationInput>) => onChange({ ...value, ...next });
  const selected = sources.filter((source) => selectedSources.includes(source.id));
  const count = sourceMode === "library" ? selected.length : value.referenceImage ? 1 : 0;
  const tagged =
    sourceMode === "library"
      ? selected.every((source) => source.tagging.trim() || value.tagging.trim())
      : Boolean(value.tagging.trim());

  return (
    <>
      <h3 className="sprite-generation__section-title">{t("spriteAnimation.settings")}</h3>
      <div className="sprite-generation__settings-fields">
        <SegmentedTabs
          ariaLabel={t("spriteAnimation.sourceMode")}
          value={sourceMode}
          onChange={(mode) => {
            if (!busy) onSourceModeChange(mode);
          }}
          items={[
            { id: "library", label: t("spriteAnimation.library") },
            { id: "file", label: t("spriteAnimation.uploadSingle") },
          ]}
        />
        {sourceMode === "library" ? (
          <p className="sprite-generation__hint">{t("spriteAnimation.libraryHint")}</p>
        ) : (
          <>
            {value.referenceImage ? (
              <div className="sprite-generation__reference-image">
                <ImageAssetThumb alt={t("spriteGeneration.reference")} src={fileUrl(value.referenceImage)} />
              </div>
            ) : null}
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("spriteAnimation.reference")}</span>
              <FilePicker
                acceptedExtensions={[".png", ".jpg", ".jpeg", ".webp"]}
                disabled={busy}
                value={value.referenceImage}
                pickLabel={t("spriteGeneration.chooseReference")}
                onPathChange={(path) => patch({ referenceImage: path })}
              />
            </label>
          </>
        )}
        <div className="sprite-generation__motion-options">
          {(["breathing", "blinking", "breeze", "loop"] as const).map((key) => (
            <Switch key={key} checked={value[key]} disabled={busy} onChange={(e) => patch({ [key]: e.target.checked })}>
              {t(`spriteAnimation.${key}`)}
            </Switch>
          ))}
        </div>
        <p className="sprite-generation__hint">{t("spriteAnimation.cameraHint")}</p>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("spriteAnimation.speed")}</span>
          <Select
            aria-label={t("spriteAnimation.speed")}
            disabled={busy}
            value={value.playbackSpeed ?? 0.75}
            onChange={(event) => patch({ playbackSpeed: Number(event.target.value) })}
          >
            <option value={0.75}>{t("spriteAnimation.speedGentle")}</option>
            <option value={0.5}>{t("spriteAnimation.speedSlower")}</option>
            <option value={1}>{t("spriteAnimation.speedOriginal")}</option>
          </Select>
          <p className="sprite-generation__hint">{t("spriteAnimation.speedHint")}</p>
        </label>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("spriteAnimation.motion")}</span>
          <TextArea
            disabled={busy}
            rows={2}
            maxLength={2000}
            value={value.motion}
            onChange={(e) => patch({ motion: e.target.value })}
            placeholder={t("spriteAnimation.motionPlaceholder")}
          />
        </label>
        <label className="field-row field-row--stack">
          <span className="field-row__label">
            {t(sourceMode === "library" ? "spriteAnimation.defaultTagging" : "spriteGeneration.tagging")}
          </span>
          <TextInput
            disabled={busy}
            maxLength={240}
            value={value.tagging}
            onChange={(e) => patch({ tagging: e.target.value })}
          />
        </label>
      </div>
      <div className="sprite-generation__plan-action">
        <p className="sprite-generation__source-count" role="status">
          {t("spriteAnimation.sourcesSelected", { count })}
        </p>
        {!busy && count > remaining ? (
          <p className="sprite-generation__notice">{t("spriteAnimation.sourceLimit", { count: remaining })}</p>
        ) : null}
        <AsyncButton
          variant={hasItems ? "default" : "primary"}
          icon={<Film aria-hidden className="button__icon" />}
          loading={loading}
          disabled={
            busy ||
            !count ||
            count > remaining ||
            !tagged ||
            !(value.breathing || value.blinking || value.breeze || value.motion.trim())
          }
          onClick={onGenerate}
        >
          {t(count > 1 ? "spriteAnimation.generateBatch" : "spriteAnimation.generate", { count })}
        </AsyncButton>
        <p className="sprite-generation__hint">{t("spriteAnimation.outputHint")}</p>
      </div>
    </>
  );
}
