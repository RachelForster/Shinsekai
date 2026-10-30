import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { Button, ImageAssetThumb } from "../../shared/ui";
import type { SpriteAnimationSource } from "./spriteAnimationSources";

interface Props {
  sources: SpriteAnimationSource[];
  selectedSources: string[];
  onSourceSelectionChange: (ids: string[]) => void;
  busy: boolean;
  remaining: number;
}

export function SpriteAnimationSourcePicker({
  sources,
  selectedSources,
  onSourceSelectionChange,
  busy,
  remaining,
}: Props) {
  const { t } = useI18n();
  const selected = sources.filter((source) => selectedSources.includes(source.id));
  const sourceName = (source: SpriteAnimationSource) =>
    t(source.origin === "generated" ? "spriteAnimation.generatedSource" : "spriteGeneration.sprite", {
      n: source.index + 1,
    });
  return (
    <div className="sprite-generation__source-picker">
      <div className="sprite-generation__source-header">
        <h4>{t("spriteAnimation.pickSources")}</h4>
        <div className="sprite-generation__source-actions">
          <Button
            variant="ghost"
            disabled={busy || !sources.length || remaining <= 0}
            onClick={() => onSourceSelectionChange(sources.slice(0, Math.max(0, remaining)).map((source) => source.id))}
          >
            {t(
              remaining > 0 && sources.length > remaining
                ? "spriteAnimation.selectFirst"
                : "spriteAnimation.selectAllSources",
              {
                count: remaining,
              },
            )}
          </Button>
          <Button variant="ghost" disabled={busy || !selected.length} onClick={() => onSourceSelectionChange([])}>
            {t("spriteAnimation.clearSources")}
          </Button>
        </div>
      </div>
      <div className="sprite-generation__source-grid" role="group" aria-label={t("spriteAnimation.pickSources")}>
        {sources.map((source) => {
          const checked = selectedSources.includes(source.id);
          const label = sourceName(source);
          return (
            <label
              key={source.id}
              className={`sprite-generation__source-card${checked ? " sprite-generation__source-card--selected" : ""}`}
            >
              <input
                type="checkbox"
                aria-label={t("spriteAnimation.selectSource", { name: label })}
                checked={checked}
                disabled={busy || (!checked && selected.length >= remaining)}
                onChange={(event) =>
                  onSourceSelectionChange(
                    event.target.checked
                      ? [...selectedSources, source.id]
                      : selectedSources.filter((id) => id !== source.id),
                  )
                }
              />
              <div className="sprite-generation__source-image">
                <ImageAssetThumb alt="" src={fileUrl(source.referenceImage)} />
              </div>
              <strong>{label}</strong>
              <span>{source.tagging || t("spriteAnimation.untaggedSource")}</span>
            </label>
          );
        })}
      </div>
      {!sources.length ? <p className="sprite-generation__hint">{t("spriteAnimation.noSources")}</p> : null}
      <p className="sprite-generation__hint">{t("spriteAnimation.sourceHint")}</p>
    </div>
  );
}
