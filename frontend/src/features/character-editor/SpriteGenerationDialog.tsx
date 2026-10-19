import { useEffect, useState } from "react";
import { ImagePlus, RefreshCw, Sparkles, Trash2 } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { baseName } from "../../shared/assets/assetText";
import { isMp4Media } from "../../shared/assets/visualMedia";
import { useI18n } from "../../shared/i18n";
import type { Character } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  Dialog,
  FilePicker,
  IconButton,
  NumberInput,
  Select,
  TaskProgress,
  TextArea,
  TextInput,
  ImageAssetThumb,
} from "../../shared/ui";
import { useSpriteGeneration } from "./useSpriteGeneration";
import { SpriteVideoFramePicker } from "./SpriteVideoFramePicker";
import "./SpriteGenerationDialog.css";

interface Props {
  character: Character;
  name: string;
  onClose: () => void;
  onImported: (character: Character) => void;
}

export function SpriteGenerationDialog({ character, name, onClose, onImported }: Props) {
  const { t } = useI18n();
  const [count, setCount] = useState(4);
  const [requirements, setRequirements] = useState("");
  const [reference, setReference] = useState("");
  const [removeBackground, setRemoveBackground] = useState(true);
  const [confirmClose, setConfirmClose] = useState(false);
  const [setupOpen, setSetupOpen] = useState(true);
  const generator = useSpriteGeneration(name, character.character_setting, onImported);
  const { items, busy, selected, activeId } = generator;
  const hasItems = items.length > 0;
  useEffect(() => setSetupOpen(!hasItems), [hasItems]);
  const existingImages = character.sprites
    .map((sprite, index) => ({ sprite, index }))
    .filter(({ sprite }) => sprite.path && !isMp4Media(sprite.path));
  const pending = items.filter((item) => !item.result || item.result.prompt !== item.prompt);
  const selectable = items.filter((item) => item.result && item.result.prompt === item.prompt && item.tagging.trim());
  const remaining = 12 - items.length;
  const validCount = Number.isInteger(count) && count >= 1 && count <= remaining;
  useEffect(() => {
    if (remaining > 0) setCount((current) => Math.min(current, remaining));
  }, [remaining]);
  const close = () => (items.length ? setConfirmClose(true) : onClose());

  return (
    <>
      <Dialog
        className="sprite-generation"
        closeLabel={t("common.close")}
        dismissible={!busy}
        onClose={close}
        open
        title={t("spriteGeneration.action")}
        footer={
          <>
            <span className="sprite-generation__selection" role="status">
              {t("spriteGeneration.selected", { count: selected.length })}
            </span>
            <Button disabled={Boolean(busy)} onClick={close}>
              {t("common.close")}
            </Button>
            <AsyncButton
              disabled={Boolean(busy) || !selected.length}
              loading={busy === "import"}
              onClick={() => void generator.save()}
              variant="primary"
            >
              {t("spriteGeneration.add", { count: selected.length })}
            </AsyncButton>
          </>
        }
      >
        <p className="sprite-generation__hint">{t("spriteGeneration.intro", { name })}</p>
        <div className="sprite-generation__setup">
          <details open={setupOpen} onToggle={(event) => setSetupOpen(event.currentTarget.open)}>
            <summary className="sprite-generation__options">
              {t("spriteGeneration.options")}
              {reference ? ` · ${baseName(reference)}` : ""}
            </summary>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("spriteGeneration.requirements")}</span>
              <TextArea
                maxLength={4000}
                disabled={Boolean(busy)}
                onChange={(event) => setRequirements(event.target.value)}
                placeholder={t("spriteGeneration.requirementsPlaceholder")}
                rows={2}
                value={requirements}
              />
            </label>
            <div className="sprite-generation__reference">
              <div>
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("spriteGeneration.reference")}</span>
                  <FilePicker
                    acceptedExtensions={[".png", ".jpg", ".jpeg", ".webp", ".bmp"]}
                    disabled={Boolean(busy)}
                    onPathChange={setReference}
                    pickLabel={t("spriteGeneration.chooseReference")}
                    value={reference}
                  />
                </label>
                {existingImages.length > 0 ? (
                  <label className="field-row field-row--stack">
                    <span className="field-row__label">{t("spriteGeneration.existingReference")}</span>
                    <Select
                      aria-label={t("spriteGeneration.existingReference")}
                      disabled={Boolean(busy)}
                      onChange={(event) => setReference(event.target.value)}
                      value={existingImages.some(({ sprite }) => sprite.path === reference) ? reference : ""}
                    >
                      <option value="">{t("spriteGeneration.chooseExisting")}</option>
                      {existingImages.map(({ sprite, index }) => (
                        <option key={`${sprite.path}-${index}`} value={sprite.path}>
                          {t("spriteGeneration.sprite", { n: index + 1 })}
                        </option>
                      ))}
                    </Select>
                  </label>
                ) : null}
                {reference ? (
                  <Button disabled={Boolean(busy)} onClick={() => setReference("")} variant="ghost">
                    {t("spriteGeneration.clearReference")}
                  </Button>
                ) : null}
              </div>
              {reference ? (
                <div className="sprite-generation__reference-image">
                  <ImageAssetThumb alt={t("spriteGeneration.reference")} src={fileUrl(reference)} />
                </div>
              ) : (
                <div className="sprite-generation__reference-empty">
                  <ImagePlus aria-hidden />
                  <span>{t("spriteGeneration.optionalReference")}</span>
                </div>
              )}
            </div>
          </details>
          <div className="sprite-generation__toolbar">
            <label className="sprite-generation__count">
              {t("spriteGeneration.count")}
              <NumberInput
                aria-label={t("spriteGeneration.count")}
                disabled={Boolean(busy) || remaining <= 0}
                min={1}
                max={remaining || 1}
                onChange={(event) => setCount(Number(event.target.value))}
                value={count}
              />
            </label>
            <AsyncButton
              disabled={Boolean(busy) || !validCount || !character.character_setting.trim()}
              icon={<Sparkles aria-hidden className="button__icon" />}
              loading={busy === "plan"}
              onClick={() => void generator.plan(count, requirements, reference)}
            >
              {t("spriteGeneration.plan")}
            </AsyncButton>
            {items.length ? (
              <AsyncButton
                disabled={Boolean(busy) || !pending.some((item) => item.prompt.trim() && item.tagging.trim())}
                loading={busy === "render"}
                onClick={() =>
                  void generator.render(
                    pending.filter((item) => item.prompt.trim() && item.tagging.trim()),
                    reference,
                    removeBackground,
                  )
                }
                variant="primary"
              >
                {t("spriteGeneration.generatePending", { count: pending.length })}
              </AsyncButton>
            ) : null}
          </div>
          <label className="sprite-generation__auto-cutout">
            <input
              type="checkbox"
              checked={removeBackground}
              disabled={Boolean(busy)}
              onChange={(event) => setRemoveBackground(event.target.checked)}
            />
            {t("spriteGeneration.autoRemoveBackground")}
          </label>
          <p className="sprite-generation__hint">{t("spriteGeneration.autoRemoveHint")}</p>
          <p className="sprite-generation__hint">
            {t("spriteGeneration.setupHint")}
            {remaining <= 0 ? ` ${t("spriteGeneration.limit")}` : ""}
          </p>
        </div>
        {generator.error ? (
          <p className="sprite-generation__error" role="alert">
            {generator.error}
          </p>
        ) : null}
        {busy ? (
          <div className="sprite-generation__progress" aria-live="polite">
            {generator.task ? (
              <TaskProgress logLimit={2} task={generator.task} />
            ) : (
              <span>{t("spriteGeneration.working")}</span>
            )}
            {busy === "render" ? (
              <Button disabled={generator.stopping} onClick={generator.stop}>
                {t(generator.stopping ? "spriteGeneration.stopping" : "spriteGeneration.stop")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {items.length ? (
          <>
            <div className="sprite-generation__toolbar">
              <Button
                disabled={Boolean(busy) || !selectable.length}
                onClick={() => generator.selectAll(selected.length !== selectable.length)}
                variant="ghost"
              >
                {t(
                  selected.length && selected.length === selectable.length
                    ? "spriteGeneration.deselectAll"
                    : "spriteGeneration.selectAll",
                )}
              </Button>
              <span className="sprite-generation__hint">{t("spriteGeneration.reviewHint")}</span>
            </div>
            <div className="sprite-generation__grid">
              {items.map((item, index) => {
                const stale = Boolean(item.result && item.result.prompt !== item.prompt);
                const title = t("spriteGeneration.sprite", { n: index + 1 });
                return (
                  <article
                    className={`sprite-generation__card${item.selected && !stale && item.tagging.trim() ? " sprite-generation__card--selected" : ""}`}
                    key={item.id}
                  >
                    <div className="sprite-generation__card-header">
                      <label>
                        <input
                          checked={item.selected && !stale && Boolean(item.tagging.trim())}
                          disabled={Boolean(busy) || !item.result || stale || !item.tagging.trim()}
                          onChange={(event) => generator.update(item.id, { selected: event.target.checked })}
                          type="checkbox"
                        />{" "}
                        {title}
                      </label>
                      <IconButton
                        disabled={Boolean(busy)}
                        label={t("spriteGeneration.remove", { n: index + 1 })}
                        onClick={() => generator.remove(item.id)}
                      >
                        <Trash2 aria-hidden className="icon-button__icon" />
                      </IconButton>
                    </div>
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
                    {stale ? <p className="sprite-generation__hint">{t("spriteGeneration.stale")}</p> : null}
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
                    {item.result && !item.result.backgroundRemoved ? (
                      <AsyncButton
                        disabled={Boolean(busy) || stale}
                        loading={busy === "cutout" && activeId === item.id}
                        onClick={() => void generator.cutout(item)}
                      >
                        {t(
                          item.result.backgroundRemovalError
                            ? "spriteGeneration.retryCutout"
                            : "spriteGeneration.cutout",
                        )}
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
                  </article>
                );
              })}
            </div>
          </>
        ) : (
          <p className="sprite-generation__empty">{t("spriteGeneration.empty")}</p>
        )}
      </Dialog>
      <AlertDialog
        body={t("spriteGeneration.discardBody")}
        cancelLabel={t("common.cancel")}
        confirmLabel={t("spriteGeneration.discard")}
        onCancel={() => setConfirmClose(false)}
        onConfirm={onClose}
        open={confirmClose}
        title={t("spriteGeneration.discardTitle")}
      />
    </>
  );
}
