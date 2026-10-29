import { ImagePlus, RefreshCw, Trash2 } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, IconButton, ImageAssetThumb, TextArea, TextInput } from "../../shared/ui";
import { SpriteVideoFramePicker } from "./SpriteVideoFramePicker";
import type { SpriteCandidate, useSpriteGeneration } from "./useSpriteGeneration";

interface Props {
  item: SpriteCandidate;
  index: number;
  generator: ReturnType<typeof useSpriteGeneration>;
  reference: string;
  removeBackground: boolean;
}

export function SpriteCandidateCard({ item, index, generator, reference, removeBackground }: Props) {
  const { t } = useI18n();
  const { busy, activeId } = generator;
  const stale = Boolean(item.result && item.result.prompt !== item.prompt);
  const selectable = Boolean(item.result && !stale && item.tagging.trim());
  const title = t("spriteGeneration.sprite", { n: index + 1 });
  const active = Boolean(busy && activeId === item.id);

  return (
    <article
      aria-label={title}
      className={`sprite-generation__card${item.selected && selectable ? " sprite-generation__card--selected" : ""}`}
    >
      <div className="sprite-generation__card-header">
        <label>
          <input
            checked={item.selected && selectable}
            disabled={Boolean(busy) || !selectable}
            onChange={(event) => generator.update(item.id, { selected: event.target.checked })}
            type="checkbox"
          />
          {title}
        </label>
        <span className="sprite-generation__badge">
          {t(
            active
              ? "spriteGeneration.working"
              : selectable
                ? "spriteGeneration.ready"
                : "spriteGeneration.notGenerated",
          )}
        </span>
        <IconButton
          disabled={Boolean(busy)}
          label={t("spriteGeneration.remove", { n: index + 1 })}
          onClick={() => generator.remove(item.id)}
        >
          <Trash2 aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("spriteGeneration.tagging")}</span>
        <TextInput
          maxLength={240}
          aria-label={`${title} ${t("spriteGeneration.tagging")}`}
          disabled={Boolean(busy)}
          onChange={(event) => generator.update(item.id, { tagging: event.target.value })}
          value={item.tagging}
        />
      </label>
      <div className="sprite-generation__preview">
        {item.result ? (
          <a
            aria-label={t("spriteGeneration.preview", { n: index + 1 })}
            href={fileUrl(item.result.path)}
            rel="noreferrer"
            target="_blank"
          >
            <ImageAssetThumb alt={title} src={fileUrl(item.result.path)} />
          </a>
        ) : (
          <div className="sprite-generation__placeholder">
            <ImagePlus aria-hidden />
            <span>{t("spriteGeneration.notGenerated")}</span>
          </div>
        )}
      </div>
      {stale ? <p className="sprite-generation__notice">{t("spriteGeneration.stale")}</p> : null}
      {item.result?.backgroundRemoved ? (
        <p className="sprite-generation__hint">{t("spriteGeneration.backgroundRemoved")}</p>
      ) : null}
      {item.result?.backgroundRemovalError ? (
        <p className="sprite-generation__error" role="alert">
          {t("spriteGeneration.backgroundRemovalFailed", { error: item.result.backgroundRemovalError })}
        </p>
      ) : null}
      {item.error ? (
        <p className="sprite-generation__error" role="alert">
          {item.error}
        </p>
      ) : null}
      <details className="sprite-generation__prompt-details">
        <summary>{t("spriteGeneration.editPrompt")}</summary>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("spriteGeneration.prompt")}</span>
          <TextArea
            maxLength={12000}
            aria-label={`${title} ${t("spriteGeneration.prompt")}`}
            disabled={Boolean(busy)}
            onChange={(event) => generator.update(item.id, { prompt: event.target.value, selected: false })}
            rows={4}
            value={item.prompt}
          />
        </label>
      </details>
      {item.result?.videoPath ? (
        <SpriteVideoFramePicker
          key={item.result.videoPath}
          path={item.result.videoPath}
          frameTime={item.result.frameTime ?? 0}
          disabled={Boolean(busy) || stale}
          title={title}
          onCapture={(seconds) => void generator.capture(item, seconds, removeBackground)}
        />
      ) : null}
      <div className="sprite-generation__card-actions">
        {item.result && !item.result.backgroundRemoved ? (
          <AsyncButton
            disabled={Boolean(busy) || stale}
            loading={busy === "cutout" && activeId === item.id}
            onClick={() => void generator.cutout(item)}
          >
            {t(item.result.backgroundRemovalError ? "spriteGeneration.retryCutout" : "spriteGeneration.cutout")}
          </AsyncButton>
        ) : null}
        <AsyncButton
          disabled={Boolean(busy) || !item.prompt.trim() || !item.tagging.trim()}
          icon={<RefreshCw aria-hidden className="button__icon" />}
          loading={busy === "render" && activeId === item.id}
          onClick={() => void generator.render([item], reference, removeBackground)}
        >
          {t(item.result ? "spriteGeneration.redraw" : "spriteGeneration.generate")}
        </AsyncButton>
      </div>
    </article>
  );
}
