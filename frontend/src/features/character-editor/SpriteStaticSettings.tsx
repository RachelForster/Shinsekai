import { ImagePlus, Sparkles } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { isVideoMedia } from "../../shared/assets/visualMedia";
import { useI18n } from "../../shared/i18n";
import type { Character, H3SpriteResolution, SpriteMattingOptions } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  FilePicker,
  NumberInput,
  Select,
  Switch,
  TextArea,
  VisualMedia,
  type MediaPreview,
} from "../../shared/ui";
import { SpriteH3ResolutionSelect } from "./SpriteH3ResolutionSelect";
import { SpriteMattingSettings } from "./SpriteMattingSettings";

interface ExistingReference {
  sprite: Character["sprites"][number];
  index: number;
}

interface SpriteStaticSettingsProps {
  busy: boolean;
  characterSetting: string;
  count: number;
  existingReferences: ExistingReference[];
  h3Resolution: H3SpriteResolution;
  hasItems: boolean;
  mattingOptions: SpriteMattingOptions;
  onCountChange: (count: number) => void;
  onH3ResolutionChange: (resolution: H3SpriteResolution) => void;
  onMattingChange: (value: SpriteMattingOptions) => void;
  onPlan: () => void;
  onPreview: (media: MediaPreview) => void;
  onReferenceChange: (reference: string) => void;
  onRemoveBackgroundChange: (remove: boolean) => void;
  onRequirementsChange: (requirements: string) => void;
  planning: boolean;
  reference: string;
  remaining: number;
  removeBackground: boolean;
  replacementTags: string[];
  requirements: string;
  validCount: boolean;
}

export function SpriteStaticSettings({
  busy,
  characterSetting,
  count,
  existingReferences,
  h3Resolution,
  hasItems,
  mattingOptions,
  onCountChange,
  onH3ResolutionChange,
  onMattingChange,
  onPlan,
  onPreview,
  onReferenceChange,
  onRemoveBackgroundChange,
  onRequirementsChange,
  planning,
  reference,
  remaining,
  removeBackground,
  replacementTags,
  requirements,
  validCount,
}: SpriteStaticSettingsProps) {
  const { t } = useI18n();

  return (
    <>
      <h3 className="sprite-generation__section-title">{t("spriteGeneration.options")}</h3>
      <div className="sprite-generation__settings-fields">
        <div className="sprite-generation__reference">
          <div className="sprite-generation__reference-image">
            {reference ? (
              <button
                type="button"
                className="sprite-generation__preview-trigger"
                aria-label={t("mediaPreview.open", { name: t("spriteGeneration.reference") })}
                onClick={() =>
                  onPreview({
                    src: fileUrl(reference),
                    title: t("spriteGeneration.reference"),
                    autoPlay: false,
                  })
                }
              >
                <VisualMedia alt={t("spriteGeneration.reference")} autoPlay={false} src={fileUrl(reference)} />
              </button>
            ) : (
              <div className="sprite-generation__reference-empty">
                <ImagePlus aria-hidden />
                <span>{t("spriteGeneration.optionalReference")}</span>
              </div>
            )}
          </div>
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("spriteGeneration.reference")}</span>
            <FilePicker
              acceptedExtensions={[
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".bmp",
                ".mp4",
                ".webm",
                ".mov",
                ".mkv",
                ".avi",
                ".m4v",
              ]}
              disabled={busy}
              onPathChange={onReferenceChange}
              pickLabel={t("spriteGeneration.chooseReference")}
              value={reference}
            />
          </label>
          {existingReferences.length > 0 ? (
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("spriteGeneration.existingReference")}</span>
              <Select
                aria-label={t("spriteGeneration.existingReference")}
                disabled={busy}
                onChange={(event) => onReferenceChange(event.target.value)}
                value={existingReferences.some(({ sprite }) => sprite.path === reference) ? reference : ""}
              >
                <option value="">{t("spriteGeneration.chooseExisting")}</option>
                {existingReferences.map(({ sprite, index }) => (
                  <option key={`${sprite.path}-${index}`} value={sprite.path}>
                    {t("spriteGeneration.sprite", { n: index + 1 })}
                    {" · "}
                    {t(isVideoMedia(sprite.path) ? "spriteGeneration.videoReference" : "spriteAnimation.sourceImage")}
                    {replacementTags[index] ? ` · ${replacementTags[index]}` : ""}
                  </option>
                ))}
              </Select>
            </label>
          ) : null}
          {reference ? (
            <Button disabled={busy} onClick={() => onReferenceChange("")} variant="ghost">
              {t("spriteGeneration.clearReference")}
            </Button>
          ) : null}
          {reference && isVideoMedia(reference) ? (
            <p className="sprite-generation__hint">{t("spriteGeneration.videoReferenceHint")}</p>
          ) : null}
          <p className="sprite-generation__hint">
            {t(reference ? "spriteGeneration.referenceHint" : "spriteGeneration.noReferenceHint")}
          </p>
          {hasItems ? <p className="sprite-generation__hint">{t("spriteGeneration.referenceChangeHint")}</p> : null}
        </div>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("spriteGeneration.requirements")}</span>
          <TextArea
            maxLength={4000}
            disabled={busy}
            onChange={(event) => onRequirementsChange(event.target.value)}
            placeholder={t("spriteGeneration.requirementsPlaceholder")}
            rows={3}
            value={requirements}
          />
        </label>
        <label className="sprite-generation__count">
          {t("spriteGeneration.count")}
          <NumberInput
            aria-label={t("spriteGeneration.count")}
            disabled={busy || remaining <= 0}
            min={1}
            max={remaining || 1}
            onChange={(event) => onCountChange(Number(event.target.value))}
            value={count}
          />
        </label>
        <SpriteH3ResolutionSelect value={h3Resolution} onChange={onH3ResolutionChange} disabled={busy} />
        <div className="sprite-generation__auto-cutout">
          <Switch
            checked={removeBackground}
            disabled={busy}
            onChange={(event) => onRemoveBackgroundChange(event.target.checked)}
          >
            {t("spriteGeneration.autoRemoveBackground")}
          </Switch>
          <p className="sprite-generation__hint">{t("spriteGeneration.autoRemoveHint")}</p>
          {removeBackground ? (
            <SpriteMattingSettings compact value={mattingOptions} disabled={busy} onChange={onMattingChange} />
          ) : null}
        </div>
      </div>
      <div className="sprite-generation__plan-action">
        {!characterSetting.trim() ? (
          <p className="sprite-generation__notice">{t("spriteGeneration.settingRequired")}</p>
        ) : null}
        {remaining <= 0 ? <p className="sprite-generation__notice">{t("spriteGeneration.limit")}</p> : null}
        <AsyncButton
          disabled={busy || !validCount || !characterSetting.trim()}
          icon={<Sparkles aria-hidden className="button__icon" />}
          loading={planning}
          onClick={onPlan}
          variant={hasItems ? "default" : "primary"}
        >
          {t(hasItems ? "spriteGeneration.morePlans" : "spriteGeneration.plan")}
        </AsyncButton>
        <p className="sprite-generation__hint">{t("spriteGeneration.planHint")}</p>
      </div>
    </>
  );
}
