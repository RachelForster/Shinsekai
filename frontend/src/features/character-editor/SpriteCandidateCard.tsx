import { useState } from "react";
import { ImagePlus, RefreshCw, Trash2 } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, IconButton, ImageAssetThumb, TextArea, TextInput, VisualMedia } from "../../shared/ui";
import { SpriteVideoFramePicker } from "./SpriteVideoFramePicker";
import { SpriteMattingStatus } from "./SpriteMattingStatus";
import type { SpriteCandidate, useSpriteGeneration } from "./useSpriteGeneration";

interface Props {
  item: SpriteCandidate;
  index: number;
  generator: ReturnType<typeof useSpriteGeneration>;
  reference: string;
  removeBackground: boolean;
  onAnimate?: (item: SpriteCandidate) => void;
  onReplace?: (item: SpriteCandidate) => void;
}

export function SpriteCandidateCard({
  item,
  index,
  generator,
  reference,
  removeBackground,
  onAnimate,
  onReplace,
}: Props) {
  const { t } = useI18n();
  const { busy, activeId } = generator;
  const [promptOpen, setPromptOpen] = useState(Boolean(item.manual));
  const animation = Boolean(item.animationInput);
  const promptLabel = t(animation ? "spriteAnimation.prompt" : "spriteGeneration.prompt");
  const stale = Boolean(item.result && item.result.prompt !== item.prompt);
  const selectable = Boolean(item.result && !stale && item.tagging.trim() && (!animation || item.result.alphaVerified));
  const title = t(animation ? "spriteAnimation.sprite" : "spriteGeneration.sprite", { n: index + 1 });
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
                : animation && item.result && !stale && !item.result.alphaVerified
                  ? "spriteAnimation.needsMatting"
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
      {item.result || !item.manual ? (
        <div className="sprite-generation__preview">
          {item.result ? (
            <a
              aria-label={t("spriteGeneration.preview", { n: index + 1 })}
              href={fileUrl(item.result.path)}
              rel="noreferrer"
              target="_blank"
            >
              {animation ? (
                <VisualMedia alt={title} src={fileUrl(item.result.path)} />
              ) : (
                <ImageAssetThumb alt={title} src={fileUrl(item.result.path)} />
              )}
            </a>
          ) : (
            <div className="sprite-generation__placeholder">
              <ImagePlus aria-hidden />
              <span>{t("spriteGeneration.notGenerated")}</span>
            </div>
          )}
        </div>
      ) : null}
      {stale ? <p className="sprite-generation__notice">{t("spriteGeneration.stale")}</p> : null}
      {item.result?.backgroundRemoved ? (
        <p className="sprite-generation__hint">
          {t(animation ? "spriteAnimation.verified" : "spriteGeneration.backgroundRemoved")}
        </p>
      ) : null}
      {animation || item.result?.backgroundRemoved ? <SpriteMattingStatus matting={item.result?.matting} /> : null}
      {item.result?.backgroundRemovalError ? (
        <p className="sprite-generation__error" role="alert">
          {t(animation ? "spriteAnimation.failed" : "spriteGeneration.backgroundRemovalFailed", {
            error: item.result.backgroundRemovalError,
          })}
        </p>
      ) : null}
      {item.error ? (
        <p className="sprite-generation__error" role="alert">
          {item.error}
        </p>
      ) : null}
      <details
        className="sprite-generation__prompt-details"
        open={promptOpen}
        onToggle={(event) => setPromptOpen(event.currentTarget.open)}
      >
        <summary>{t(animation ? "spriteAnimation.viewPrompt" : "spriteGeneration.editPrompt")}</summary>
        <p className="sprite-generation__hint">
          {t(animation ? "spriteAnimation.customPromptHint" : "spriteGeneration.manualPromptHint")}
        </p>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{promptLabel}</span>
          <TextArea
            autoFocus={item.manual}
            placeholder={t(
              animation ? "spriteAnimation.manualPromptPlaceholder" : "spriteGeneration.manualPromptPlaceholder",
            )}
            maxLength={12000}
            aria-label={`${title} ${promptLabel}`}
            disabled={Boolean(busy)}
            onChange={(event) =>
              generator.update(item.id, {
                prompt: event.target.value,
                selected: false,
                ...(item.animationInput
                  ? { animationInput: { ...item.animationInput, customPrompt: event.target.value } }
                  : {}),
              })
            }
            rows={4}
            value={item.prompt}
          />
        </label>
      </details>
      {item.result?.videoPath && !animation ? (
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
        {item.result && onReplace ? (
          <AsyncButton disabled={Boolean(busy) || !selectable} onClick={() => onReplace(item)}>
            {t("spriteGeneration.replace")}
          </AsyncButton>
        ) : null}
        {item.result && !stale && onAnimate ? (
          <AsyncButton disabled={Boolean(busy)} onClick={() => onAnimate(item)}>
            {t(animation ? "spriteAnimation.fromFirstFrame" : "spriteAnimation.fromStatic")}
          </AsyncButton>
        ) : null}
        {item.result && (!item.result.backgroundRemoved || (animation && item.result.videoPath)) ? (
          <AsyncButton
            disabled={Boolean(busy) || stale}
            loading={busy === "cutout" && activeId === item.id}
            title={animation ? t("spriteMatting.retryHint") : undefined}
            onClick={() => void generator.cutout(item)}
          >
            {t(
              animation
                ? item.result.alphaVerified
                  ? "spriteMatting.refineAgain"
                  : "spriteAnimation.retryMatting"
                : item.result.backgroundRemovalError
                  ? "spriteGeneration.retryCutout"
                  : "spriteGeneration.cutout",
            )}
          </AsyncButton>
        ) : null}
        <AsyncButton
          disabled={
            Boolean(busy) ||
            ((!animation || item.animationInput?.customPrompt !== undefined) && !item.prompt.trim()) ||
            !item.tagging.trim()
          }
          icon={<RefreshCw aria-hidden className="button__icon" />}
          loading={(busy === "render" || busy === "animate") && activeId === item.id}
          onClick={() =>
            void (item.animationInput
              ? generator.animate(item.animationInput, item)
              : generator.render([item], reference, removeBackground))
          }
        >
          {t(item.result ? "spriteGeneration.redraw" : "spriteGeneration.generate")}
        </AsyncButton>
      </div>
    </article>
  );
}
