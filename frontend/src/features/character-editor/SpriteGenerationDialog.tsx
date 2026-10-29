import { useEffect, useRef, useState } from "react";
import { Check, ImagePlus, Sparkles } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { isMp4Media } from "../../shared/assets/visualMedia";
import { useI18n } from "../../shared/i18n";
import type { Character } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  Dialog,
  EmptyState,
  FilePicker,
  NumberInput,
  Select,
  Switch,
  TaskProgress,
  TextArea,
  ImageAssetThumb,
} from "../../shared/ui";
import { useSpriteGeneration } from "./useSpriteGeneration";
import { SpriteCandidateCard } from "./SpriteCandidateCard";
import { SpriteGenerationSetupGuide } from "./SpriteGenerationSetupGuide";
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
  const [guideOpen, setGuideOpen] = useState(true);
  const workspaceBodyRef = useRef<HTMLDivElement>(null);
  const generator = useSpriteGeneration(name, character.character_setting, onImported);
  const { items, busy, selected } = generator;
  const hasItems = items.length > 0;
  useEffect(() => setGuideOpen(!hasItems), [hasItems]);
  const existingImages = character.sprites
    .map((sprite, index) => ({ sprite, index }))
    .filter(({ sprite }) => sprite.path && !isMp4Media(sprite.path));
  const pending = items.filter((item) => !item.result || item.result.prompt !== item.prompt);
  const selectable = items.filter((item) => item.result && item.result.prompt === item.prompt && item.tagging.trim());
  const renderable = pending.filter((item) => item.prompt.trim() && item.tagging.trim());
  const currentStep = !hasItems ? 0 : selectable.length ? 2 : 1;
  const steps = ["spriteGeneration.stepPlan", "spriteGeneration.stepGenerate", "spriteGeneration.stepSave"] as const;
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
            <div className="sprite-generation__selection" role="status">
              <strong>{t("spriteGeneration.selected", { count: selected.length })}</strong>
              <span>{t("spriteGeneration.saveHint")}</span>
            </div>
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
        <div className="sprite-generation__journey">
          <p className="sprite-generation__hint">{t("spriteGeneration.intro", { name })}</p>
          <ol className="sprite-generation__steps" aria-label={t("spriteGeneration.stepsLabel")}>
            {steps.map((step, index) => (
              <li
                key={step}
                aria-current={index === currentStep ? "step" : undefined}
                data-complete={index < currentStep}
              >
                <span className="sprite-generation__step-number" aria-hidden>
                  {index < currentStep ? <Check size={14} /> : index + 1}
                </span>
                {t(step)}
              </li>
            ))}
          </ol>
        </div>
        <div className="sprite-generation__layout">
          <aside className="sprite-generation__settings" aria-label={t("spriteGeneration.options")}>
            <h3 className="sprite-generation__section-title">{t("spriteGeneration.options")}</h3>
            <div className="sprite-generation__settings-fields">
              <div className="sprite-generation__reference">
                <div className="sprite-generation__reference-image">
                  {reference ? (
                    <ImageAssetThumb alt={t("spriteGeneration.reference")} src={fileUrl(reference)} />
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
                <p className="sprite-generation__hint">
                  {t(reference ? "spriteGeneration.referenceHint" : "spriteGeneration.noReferenceHint")}
                </p>
                {hasItems ? (
                  <p className="sprite-generation__hint">{t("spriteGeneration.referenceChangeHint")}</p>
                ) : null}
              </div>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("spriteGeneration.requirements")}</span>
                <TextArea
                  maxLength={4000}
                  disabled={Boolean(busy)}
                  onChange={(event) => setRequirements(event.target.value)}
                  placeholder={t("spriteGeneration.requirementsPlaceholder")}
                  rows={3}
                  value={requirements}
                />
              </label>
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
              <div className="sprite-generation__auto-cutout">
                <Switch
                  checked={removeBackground}
                  disabled={Boolean(busy)}
                  onChange={(event) => setRemoveBackground(event.target.checked)}
                >
                  {t("spriteGeneration.autoRemoveBackground")}
                </Switch>
                <p className="sprite-generation__hint">{t("spriteGeneration.autoRemoveHint")}</p>
              </div>
            </div>
            <div className="sprite-generation__plan-action">
              {!character.character_setting.trim() ? (
                <p className="sprite-generation__notice">{t("spriteGeneration.settingRequired")}</p>
              ) : null}
              {remaining <= 0 ? <p className="sprite-generation__notice">{t("spriteGeneration.limit")}</p> : null}
              <AsyncButton
                disabled={Boolean(busy) || !validCount || !character.character_setting.trim()}
                icon={<Sparkles aria-hidden className="button__icon" />}
                loading={busy === "plan"}
                onClick={() => void generator.plan(count, requirements, reference)}
                variant={hasItems ? "default" : "primary"}
              >
                {t(hasItems ? "spriteGeneration.morePlans" : "spriteGeneration.plan")}
              </AsyncButton>
              <p className="sprite-generation__hint">{t("spriteGeneration.planHint")}</p>
            </div>
          </aside>
          <section className="sprite-generation__workspace" aria-label={t("spriteGeneration.workspaceTitle")}>
            <div className="sprite-generation__workspace-header">
              <div>
                <h3 className="sprite-generation__section-title">{t("spriteGeneration.workspaceTitle")}</h3>
                <p className="sprite-generation__hint" role="status">
                  {t("spriteGeneration.workspaceSummary", { ready: selectable.length, pending: pending.length })}
                </p>
              </div>
              <div className="sprite-generation__toolbar">
                <Button
                  aria-expanded={guideOpen}
                  onClick={() => {
                    setGuideOpen(!guideOpen);
                    if (!guideOpen && workspaceBodyRef.current) workspaceBodyRef.current.scrollTop = 0;
                  }}
                  variant="ghost"
                >
                  {t("spriteGeneration.resources")}
                </Button>
                {hasItems ? (
                  <AsyncButton
                    disabled={Boolean(busy) || !renderable.length}
                    loading={busy === "render"}
                    onClick={() => void generator.render(renderable, reference, removeBackground)}
                    variant="primary"
                  >
                    {t("spriteGeneration.generatePending", { count: renderable.length })}
                  </AsyncButton>
                ) : null}
              </div>
            </div>
            <div className="sprite-generation__feedback">
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
            </div>
            <div className="sprite-generation__workspace-body" ref={workspaceBodyRef}>
              {guideOpen && hasItems ? <SpriteGenerationSetupGuide /> : null}
              {hasItems ? (
                <>
                  <div className="sprite-generation__review-toolbar">
                    <p className="sprite-generation__hint">{t("spriteGeneration.reviewHint")}</p>
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
                  </div>
                  <div className="sprite-generation__grid">
                    {items.map((item, index) => (
                      <SpriteCandidateCard
                        key={item.id}
                        item={item}
                        index={index}
                        generator={generator}
                        reference={reference}
                        removeBackground={removeBackground}
                      />
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState title={t("spriteGeneration.emptyTitle")} body={t("spriteGeneration.empty")} />
              )}
              {guideOpen && !hasItems ? <SpriteGenerationSetupGuide /> : null}
            </div>
          </section>
        </div>
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
