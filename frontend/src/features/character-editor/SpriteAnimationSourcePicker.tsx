import { Film, Image as ImageIcon } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { isVideoMedia } from "../../shared/assets/visualMedia";
import { useI18n } from "../../shared/i18n";
import { Button, VisualMedia } from "../../shared/ui";
import type { SpriteAnimationSource } from "./spriteAnimationSources";

interface Props {
  sources: SpriteAnimationSource[];
  selectedSources: string[];
  onSourceSelectionChange: (ids: string[]) => void;
  busy: boolean;
  remaining: number;
  title?: string;
  hint?: string;
  untaggedLabel?: string;
  emptyHint?: string;
}

export function SpriteAnimationSourcePicker({
  sources,
  selectedSources,
  onSourceSelectionChange,
  busy,
  remaining,
  title,
  hint,
  untaggedLabel,
  emptyHint,
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
        <h4>{title ?? t("spriteAnimation.pickSources")}</h4>
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
      <div
        className="sprite-generation__source-grid"
        role="group"
        aria-label={title ?? t("spriteAnimation.pickSources")}
      >
        {sources.map((source) => {
          const checked = selectedSources.includes(source.id);
          const label = sourceName(source);
          const video = isVideoMedia(source.referenceImage);
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
                <VisualMedia alt="" autoPlay={false} loading="lazy" src={fileUrl(source.referenceImage)} />
                <span className="sprite-generation__source-type">
                  {video ? <Film size={12} aria-hidden /> : <ImageIcon size={12} aria-hidden />}
                  {t(video ? "spriteAnimation.sourceAnimated" : "spriteAnimation.sourceImage")}
                </span>
              </div>
              <strong>{label}</strong>
              <span>{source.tagging || untaggedLabel || t("spriteAnimation.untaggedSource")}</span>
            </label>
          );
        })}
      </div>
      {!sources.length ? (
        <p className="sprite-generation__hint">{emptyHint || t("spriteAnimation.noSources")}</p>
      ) : null}
      <p className="sprite-generation__hint">{hint ?? t("spriteAnimation.sourceHint")}</p>
    </div>
  );
}
