import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { Check, ImagePlus, Plus, Sparkles } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { isVideoMedia } from "../../shared/assets/visualMedia";
import { tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import type { Character, CharacterSpriteAnimationInput } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  ColorInput,
  Dialog,
  EmptyState,
  FilePicker,
  NumberInput,
  Select,
  SegmentedTabs,
  Switch,
  TaskProgress,
  TextArea,
  ImageAssetThumb,
  VisualMedia,
} from "../../shared/ui";
import { SpriteAnimationSettings } from "./SpriteAnimationSettings";
import { SpriteMattingSettings } from "./SpriteMattingSettings";
import { SpriteAnimationSourcePicker } from "./SpriteAnimationSourcePicker";
import { spriteAnimationSources } from "./spriteAnimationSources";
import { useSpriteGeneration, type SpriteCandidate } from "./useSpriteGeneration";
import { SpriteCandidateCard } from "./SpriteCandidateCard";
import { SpriteGenerationSetupGuide } from "./SpriteGenerationSetupGuide";
import { SpriteTransitionWorkspace } from "./SpriteTransitionWorkspace";
import { useSpriteTransitions } from "./useSpriteTransitions";
import "./SpriteGenerationDialog.css";

interface Props {
  character: Character;
  name: string;
  onClose: () => void;
  onImported: (character: Character, replacedIndex?: number | number[]) => void;
}

export function SpriteGenerationDialog({ character, name, onClose, onImported }: Props) {
  const { t } = useI18n();
  const tabsId = useId();
  const [mode, setMode] = useState<"static" | "animation" | "transition">("static");
  const [animationSourceMode, setAnimationSourceMode] = useState<"library" | "file">("library");
  const [animationSelection, setAnimationSelection] = useState<string[]>([]);
  const [animationSourcesOpen, setAnimationSourcesOpen] = useState(true);
  const [animationInput, setAnimationInput] = useState<CharacterSpriteAnimationInput>({
    name,
    referenceImage: "",
    tagging: "平静，站立",
    breathing: true,
    blinking: true,
    breeze: false,
    loop: true,
    motion: "",
    playbackSpeed: 0.75,
    mattingModel: "toonout",
    autoScreen: false,
    alphaMatting: false,
  });
  const [count, setCount] = useState(4);
  const [requirements, setRequirements] = useState("");
  const [reference, setReference] = useState("");
  const [removeBackground, setRemoveBackground] = useState(true);
  const [confirmClose, setConfirmClose] = useState(false);
  const [replacementCandidate, setReplacementCandidate] = useState<SpriteCandidate | null>(null);
  const [replacementIndex, setReplacementIndex] = useState("");
  const [guideOpen, setGuideOpen] = useState(true);
  const [coloredPreview, setColoredPreview] = useState(false);
  const [previewColor, setPreviewColor] = useState("#5577aa");
  const previewProps = {
    "data-sprite-preview-background": coloredPreview || undefined,
    style: { "--sprite-preview-color": previewColor } as CSSProperties,
  };
  const workspaceBodyRef = useRef<HTMLDivElement>(null);
  const mattingOptions = {
    mattingModel: animationInput.mattingModel ?? "toonout",
    autoScreen: animationInput.autoScreen ?? false,
    alphaMatting: animationInput.alphaMatting ?? false,
  };
  const generator = useSpriteGeneration(
    name,
    character.character_setting,
    onImported,
    character.sprites,
    mattingOptions,
  );
  const transitions = useSpriteTransitions(character, name, onImported, mattingOptions);
  const busy = generator.busy || transitions.busy;
  const animationSources = spriteAnimationSources(character, generator.items);
  const animationInputs =
    animationSourceMode === "library"
      ? animationSources
          .filter((source) => animationSelection.includes(source.id))
          .map((source) => ({
            ...animationInput,
            referenceImage: source.referenceImage,
            tagging: source.tagging.trim() || animationInput.tagging,
          }))
      : animationInput.referenceImage
        ? [animationInput]
        : [];
  const items = generator.items.filter((item) => Boolean(item.animationInput) === (mode === "animation"));
  const selectedSprites = generator.selected.filter((item) => Boolean(item.animationInput) === (mode === "animation"));
  const selected = mode === "transition" ? transitions.selected : selectedSprites;
  const originals = selectedSprites.flatMap((item) => (item.original ? [item.original] : []));
  const replacementIssue =
    originals.length !== selectedSprites.length
      ? "spriteGeneration.replaceMissing"
      : originals.some((target) => character.sprites[target.index]?.path !== target.path)
        ? "spriteGeneration.replaceChanged"
        : new Set(originals.map((target) => target.index)).size !== originals.length
          ? "spriteGeneration.replaceDuplicate"
          : undefined;
  const hasItems = items.length > 0;
  useEffect(() => {
    setGuideOpen(!hasItems);
    setAnimationSourcesOpen(!hasItems);
  }, [hasItems]);
  const existingImages = character.sprites
    .map((sprite, index) => ({ sprite, index }))
    .filter(({ sprite }) => sprite.path && !isVideoMedia(sprite.path));
  const pending = items.filter(
    (item) => !item.result || item.result.prompt !== item.prompt || (item.animationInput && !item.result.alphaVerified),
  );
  const selectable = items.filter(
    (item) =>
      item.result &&
      item.result.prompt === item.prompt &&
      item.tagging.trim() &&
      (!item.animationInput || item.result.alphaVerified),
  );
  const renderable = pending.filter((item) => item.prompt.trim() && item.tagging.trim());
  const animationPending = pending.filter(
    (item) =>
      item.animationInput &&
      (!item.result || item.result.prompt !== item.prompt) &&
      (item.animationInput.customPrompt === undefined || item.prompt.trim()) &&
      item.tagging.trim(),
  );
  const currentStep =
    mode === "transition"
      ? !transitions.items.length
        ? 0
        : transitions.items.some((item) => item.result?.alphaVerified)
          ? 2
          : 1
      : !hasItems
        ? 0
        : selectable.length
          ? 2
          : 1;
  const steps =
    mode === "transition"
      ? (["spriteTransition.stepSource", "spriteTransition.stepGenerate", "spriteTransition.stepSave"] as const)
      : mode === "animation"
        ? (["spriteAnimation.stepSource", "spriteAnimation.stepMotion", "spriteAnimation.stepSave"] as const)
        : (["spriteGeneration.stepPlan", "spriteGeneration.stepGenerate", "spriteGeneration.stepSave"] as const);
  const remaining = 12 - generator.items.length;
  const validCount = Number.isInteger(count) && count >= 1 && count <= remaining;
  useEffect(() => {
    if (remaining > 0) setCount((current) => Math.min(current, remaining));
  }, [remaining]);
  const close = () => (generator.items.length || transitions.hasDrafts ? setConfirmClose(true) : onClose());
  const replacementTarget = replacementIndex === "" ? undefined : character.sprites[Number(replacementIndex)];
  const replacementTags = tagContents(character.emotion_tags, character.sprites.length);

  return (
    <>
      <Dialog
        className="sprite-generation"
        closeLabel={t("common.close")}
        dismissible={!busy}
        onClose={close}
        open
        title={t("spriteGeneration.action")}
        headerActions={
          <div className="sprite-generation__preview-background" title={t("spriteGeneration.previewBackgroundHint")}>
            <Switch checked={coloredPreview} onChange={(event) => setColoredPreview(event.target.checked)}>
              {t("spriteGeneration.previewBackground")}
            </Switch>
            {coloredPreview ? (
              <ColorInput
                aria-label={t("spriteGeneration.previewColor")}
                value={previewColor}
                onChange={(event) => setPreviewColor(event.target.value)}
              />
            ) : null}
          </div>
        }
        footer={
          <>
            <div className="sprite-generation__selection" role="status">
              <strong>
                {t(mode === "transition" ? "spriteTransition.selected" : "spriteGeneration.selected", {
                  count: selected.length,
                })}
              </strong>
              <span>
                {t(
                  mode === "transition"
                    ? "spriteTransition.saveHint"
                    : selected.length
                      ? (replacementIssue ?? "spriteGeneration.replaceSelectedHint")
                      : "spriteGeneration.saveHint",
                )}
              </span>
            </div>
            <Button disabled={Boolean(busy)} onClick={close}>
              {t("common.close")}
            </Button>
            {mode !== "transition" ? (
              <AsyncButton
                disabled={Boolean(busy) || !selectedSprites.length || Boolean(replacementIssue)}
                loading={busy === "replace"}
                title={t(replacementIssue ?? "spriteGeneration.replaceSelectedHint")}
                onClick={() => void generator.replaceSelected(selectedSprites)}
              >
                {t("spriteGeneration.replaceSelected", { count: selectedSprites.length })}
              </AsyncButton>
            ) : null}
            <AsyncButton
              disabled={Boolean(busy) || !selected.length}
              loading={busy === "import" || busy === "transition-save"}
              onClick={() =>
                mode === "transition"
                  ? void transitions.save()
                  : void generator.save(
                      generator.selected.filter((item) => Boolean(item.animationInput) === (mode === "animation")),
                    )
              }
              variant="primary"
            >
              {t(mode === "transition" ? "spriteTransition.save" : "spriteGeneration.add", { count: selected.length })}
            </AsyncButton>
          </>
        }
      >
        <div className="sprite-generation__journey">
          <SegmentedTabs
            idPrefix={tabsId}
            ariaLabel={t("spriteAnimation.mode")}
            value={mode}
            onChange={(value) => {
              if (!busy) setMode(value);
            }}
            items={[
              { id: "static", label: t("spriteAnimation.staticTab") },
              { id: "animation", label: t("spriteAnimation.animationTab") },
              { id: "transition", label: t("spriteTransition.tab") },
            ]}
          />
          <p className="sprite-generation__hint">
            {t(
              mode === "transition"
                ? "spriteTransition.intro"
                : mode === "animation"
                  ? "spriteAnimation.intro"
                  : "spriteGeneration.intro",
              { name },
            )}
          </p>
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
        {mode === "transition" ? (
          <div
            role="tabpanel"
            id={`${tabsId}-panel-transition`}
            aria-labelledby={`${tabsId}-transition`}
            className="sprite-transitions__panel"
            {...previewProps}
          >
            <SpriteTransitionWorkspace
              character={character}
              controller={transitions}
              mattingOptions={mattingOptions}
              onMattingChange={(value) => setAnimationInput((current) => ({ ...current, ...value }))}
            />
          </div>
        ) : (
          <div
            className="sprite-generation__layout"
            role="tabpanel"
            id={`${tabsId}-panel-${mode}`}
            aria-labelledby={`${tabsId}-${mode}`}
            {...previewProps}
          >
            <aside className="sprite-generation__settings" aria-label={t("spriteGeneration.options")}>
              {mode === "animation" ? (
                <SpriteAnimationSettings
                  value={animationInput}
                  sources={animationSources}
                  selectedSources={animationSelection}
                  sourceMode={animationSourceMode}
                  onSourceModeChange={setAnimationSourceMode}
                  onChange={setAnimationInput}
                  onGenerate={() => void generator.animateBatch(animationInputs)}
                  busy={Boolean(busy)}
                  loading={busy === "animate"}
                  remaining={remaining}
                  hasItems={hasItems}
                />
              ) : (
                <>
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
                      {removeBackground ? (
                        <SpriteMattingSettings
                          compact
                          value={mattingOptions}
                          disabled={Boolean(busy)}
                          onChange={(value) => setAnimationInput((current) => ({ ...current, ...value }))}
                        />
                      ) : null}
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
                </>
              )}
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
                    disabled={Boolean(busy) || remaining <= 0 || (mode === "animation" && animationInputs.length !== 1)}
                    icon={<Plus aria-hidden className="button__icon" />}
                    tooltip={
                      mode === "animation" && animationInputs.length !== 1
                        ? t("spriteGeneration.manualSourceHint")
                        : t("spriteGeneration.manualPromptHint")
                    }
                    onClick={() => {
                      generator.addManual(mode === "animation" ? animationInputs[0] : undefined);
                      setGuideOpen(false);
                      setAnimationSourcesOpen(false);
                    }}
                  >
                    {t("spriteGeneration.manualSingle")}
                  </Button>
                  {mode === "animation" && animationSourceMode === "library" ? (
                    <Button
                      variant="ghost"
                      aria-expanded={animationSourcesOpen}
                      onClick={() => {
                        setAnimationSourcesOpen(!animationSourcesOpen);
                        if (workspaceBodyRef.current) workspaceBodyRef.current.scrollTop = 0;
                      }}
                    >
                      {t("spriteAnimation.chooseSources")}
                    </Button>
                  ) : null}
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
                  {mode === "static" && renderable.length > 0 ? (
                    <AsyncButton
                      disabled={Boolean(busy) || !renderable.length}
                      loading={busy === "render"}
                      onClick={() => void generator.render(renderable, reference, removeBackground)}
                      variant="primary"
                    >
                      {t("spriteGeneration.generatePending", { count: renderable.length })}
                    </AsyncButton>
                  ) : null}
                  {mode === "animation" && animationPending.length ? (
                    <AsyncButton
                      disabled={Boolean(busy)}
                      loading={busy === "animate"}
                      onClick={() => void generator.animatePending(animationPending)}
                      variant="primary"
                    >
                      {t("spriteAnimation.generatePending", { count: animationPending.length })}
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
                    {generator.queue && generator.queue.total > 1 ? (
                      <strong className="sprite-generation__queue-count">
                        {t("spriteAnimation.queueProgress", generator.queue)}
                      </strong>
                    ) : null}
                    {generator.task ? (
                      <TaskProgress compact logLimit={0} task={generator.task} />
                    ) : (
                      <span className="sprite-generation__working">{t("spriteGeneration.working")}</span>
                    )}
                    {busy === "render" || (busy === "animate" && generator.queue && generator.queue.total > 1) ? (
                      <Button disabled={generator.stopping} onClick={generator.stop}>
                        {t(generator.stopping ? "spriteGeneration.stopping" : "spriteGeneration.stop")}
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div className="sprite-generation__workspace-body" ref={workspaceBodyRef}>
                {mode === "animation" && animationSourceMode === "library" && animationSourcesOpen ? (
                  <SpriteAnimationSourcePicker
                    sources={animationSources}
                    selectedSources={animationSelection}
                    onSourceSelectionChange={setAnimationSelection}
                    busy={Boolean(busy)}
                    remaining={remaining}
                  />
                ) : null}
                {guideOpen && hasItems ? <SpriteGenerationSetupGuide /> : null}
                {hasItems ? (
                  <>
                    <div className="sprite-generation__review-toolbar">
                      <p className="sprite-generation__hint">{t("spriteGeneration.reviewHint")}</p>
                      <Button
                        disabled={Boolean(busy) || !selectable.length}
                        onClick={() => generator.selectAll(selected.length !== selectable.length, items)}
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
                          onReplace={
                            character.sprites.length
                              ? (item) => {
                                  const original = item.original;
                                  const source = item.animationInput?.referenceImage || reference;
                                  const index =
                                    original && character.sprites[original.index]?.path === original.path
                                      ? original.index
                                      : character.sprites.findIndex((sprite) => sprite.path === source);
                                  setReplacementIndex(index >= 0 ? String(index) : "");
                                  generator.clearError();
                                  setReplacementCandidate(item);
                                }
                              : undefined
                          }
                          onAnimate={(item) => {
                            if (!item.result) return;
                            setAnimationInput((current) => ({
                              ...current,
                              referenceImage: item.result!.path,
                              tagging: item.tagging,
                            }));
                            setAnimationSelection([`generated:${item.id}`]);
                            setAnimationSourceMode("library");
                            setAnimationSourcesOpen(true);
                            setMode("animation");
                          }}
                        />
                      ))}
                    </div>
                  </>
                ) : mode === "animation" && animationSourceMode === "library" && animationSourcesOpen ? null : (
                  <EmptyState
                    title={t(mode === "animation" ? "spriteAnimation.emptyTitle" : "spriteGeneration.emptyTitle")}
                    body={t(mode === "animation" ? "spriteAnimation.empty" : "spriteGeneration.empty")}
                  />
                )}
                {guideOpen && !hasItems ? <SpriteGenerationSetupGuide /> : null}
              </div>
            </section>
          </div>
        )}
      </Dialog>
      <Dialog
        open={Boolean(replacementCandidate)}
        title={t("spriteGeneration.replace")}
        closeLabel={t("common.close")}
        dismissible={!busy}
        onClose={() => setReplacementCandidate(null)}
        footer={
          <>
            <Button disabled={Boolean(busy)} onClick={() => setReplacementCandidate(null)}>
              {t("common.cancel")}
            </Button>
            <AsyncButton
              variant="primary"
              disabled={Boolean(busy) || !replacementTarget}
              loading={busy === "replace"}
              onClick={async () => {
                if (!replacementCandidate || !replacementTarget) return;
                if (await generator.replace(replacementCandidate, Number(replacementIndex), replacementTarget.path))
                  setReplacementCandidate(null);
              }}
            >
              {t("spriteGeneration.confirmReplace")}
            </AsyncButton>
          </>
        }
      >
        <p>{t("spriteGeneration.replaceHint")}</p>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("spriteGeneration.replaceTarget")}</span>
          <Select
            aria-label={t("spriteGeneration.replaceTarget")}
            value={replacementIndex}
            disabled={Boolean(busy)}
            onChange={(event) => setReplacementIndex(event.target.value)}
          >
            <option value="">{t("spriteGeneration.chooseReplaceTarget")}</option>
            {character.sprites.map((sprite, index) => (
              <option value={index} key={`${index}:${sprite.path}`}>
                {t("spriteGeneration.sprite", { n: index + 1 })}
                {replacementTags[index] ? ` · ${replacementTags[index]}` : ""}
              </option>
            ))}
          </Select>
        </label>
        <div className="sprite-generation__replace-previews" {...previewProps}>
          <div>
            <p>{t("spriteGeneration.originalSprite")}</p>
            <div className="sprite-generation__preview">
              {replacementTarget ? (
                <VisualMedia alt={t("spriteGeneration.originalSprite")} src={fileUrl(replacementTarget.path)} />
              ) : null}
            </div>
          </div>
          <div>
            <p>{t("spriteGeneration.replacementSprite")}</p>
            <div className="sprite-generation__preview">
              {replacementCandidate?.result ? (
                <VisualMedia
                  alt={t("spriteGeneration.replacementSprite")}
                  src={fileUrl(replacementCandidate.result.path)}
                />
              ) : null}
            </div>
          </div>
        </div>
        {generator.error ? (
          <p className="sprite-generation__error" role="alert">
            {generator.error}
          </p>
        ) : null}
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
