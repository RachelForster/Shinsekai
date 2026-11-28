import { useEffect, useId, useState, type CSSProperties } from "react";
import { Check } from "lucide-react";

import { tagContents } from "../../shared/assets/assetText";
import { DEFAULT_SPRITE_TAGGING } from "../../shared/constants";
import { useI18n } from "../../shared/i18n";
import type { Character, CharacterSpriteAnimationInput, H3SpriteResolution } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  ColorInput,
  MediaPreviewDialog,
  Select,
  SegmentedTabs,
  Switch,
  type MediaPreview,
} from "../../shared/ui";
import { SpriteAnimationSettings } from "./SpriteAnimationSettings";
import { spriteAnimationSources } from "./spriteAnimationSources";
import { useSpriteGeneration, type SpriteCandidate } from "./useSpriteGeneration";
import { SpriteGenerationPageFrame } from "./SpriteGenerationFrame";
import { SpriteGenerationWorkspace } from "./SpriteGenerationWorkspace";
import { SpriteReplaceDialog } from "./SpriteReplaceDialog";
import { SpriteStaticSettings } from "./SpriteStaticSettings";
import { SpriteTransitionWorkspace } from "./SpriteTransitionWorkspace";
import { useSpriteTransitions } from "./useSpriteTransitions";
import { SpriteMouthWorkspace } from "./SpriteMouthWorkspace";
import { useSpriteMouths } from "./useSpriteMouths";
import "./SpriteGenerationPage.css";

interface Props {
  character: Character;
  name: string;
  onClose: () => void;
  onImported: (character: Character, replacedIndex?: number | number[]) => void;
}

export function SpriteGenerationPage({ character, name, onClose, onImported }: Props) {
  const { t } = useI18n();
  const tabsId = useId();
  const [mode, setMode] = useState<"static" | "animation" | "transition" | "mouth">("static");
  const [animationSourceMode, setAnimationSourceMode] = useState<"library" | "file">("library");
  const [animationSelection, setAnimationSelection] = useState<string[]>([]);
  const [animationSourcesOpen, setAnimationSourcesOpen] = useState(true);
  const [animationInput, setAnimationInput] = useState<CharacterSpriteAnimationInput>({
    name,
    referenceImage: "",
    tagging: DEFAULT_SPRITE_TAGGING,
    breathing: true,
    blinking: true,
    breeze: false,
    loop: true,
    motion: "",
    playbackSpeed: 0.75,
    h3Resolution: "workflow",
    mattingModel: "toonout",
    autoScreen: false,
    alphaMatting: false,
  });
  const [count, setCount] = useState(4);
  const [requirements, setRequirements] = useState("");
  const [reference, setReference] = useState("");
  const [removeBackground, setRemoveBackground] = useState(true);
  const [h3Resolution, setH3Resolution] = useState<H3SpriteResolution>("workflow");
  const [confirmClose, setConfirmClose] = useState(false);
  const [replacementCandidate, setReplacementCandidate] = useState<SpriteCandidate | null>(null);
  const [replacementIndex, setReplacementIndex] = useState("");
  const [guideOpen, setGuideOpen] = useState(true);
  const [coloredPreview, setColoredPreview] = useState(false);
  const [previewSize, setPreviewSize] = useState("standard");
  const [previewColor, setPreviewColor] = useState("#5577aa");
  const [mediaPreview, setMediaPreview] = useState<MediaPreview | null>(null);
  const previewProps = {
    "data-sprite-preview-background": coloredPreview || undefined,
    "data-sprite-preview-size": previewSize,
    style: { "--sprite-preview-color": previewColor } as CSSProperties,
  };
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
    h3Resolution,
    animationInput.h3Resolution,
  );
  const transitions = useSpriteTransitions(character, name, onImported, mattingOptions);
  const mouths = useSpriteMouths(character, name, onImported, Boolean(generator.busy || transitions.busy));
  const busy = generator.busy || transitions.busy || mouths.busy;
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
  const selected = mode === "mouth" ? mouths.selected : mode === "transition" ? transitions.selected : selectedSprites;
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
  const existingReferences = character.sprites
    .map((sprite, index) => ({ sprite, index }))
    .filter(({ sprite }) => sprite.path);
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
    mode === "mouth"
      ? !mouths.items.length
        ? 0
        : mouths.items.some((item) => item.result?.ready)
          ? 2
          : 1
      : mode === "transition"
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
    mode === "mouth"
      ? (["spriteMouth.stepSource", "spriteMouth.stepGenerate", "spriteMouth.stepSave"] as const)
      : mode === "transition"
        ? (["spriteTransition.stepSource", "spriteTransition.stepGenerate", "spriteTransition.stepSave"] as const)
        : mode === "animation"
          ? (["spriteAnimation.stepSource", "spriteAnimation.stepMotion", "spriteAnimation.stepSave"] as const)
          : (["spriteGeneration.stepPlan", "spriteGeneration.stepGenerate", "spriteGeneration.stepSave"] as const);
  const remaining = 12 - generator.items.length;
  const validCount = Number.isInteger(count) && count >= 1 && count <= remaining;
  useEffect(() => {
    if (remaining > 0) setCount((current) => Math.min(current, remaining));
  }, [remaining]);
  const close = () =>
    generator.items.length || transitions.hasDrafts || mouths.hasDrafts ? setConfirmClose(true) : onClose();
  const replacementTags = tagContents(character.emotion_tags, character.sprites.length);
  const introText = t(
    mode === "mouth"
      ? "spriteMouth.intro"
      : mode === "transition"
        ? "spriteTransition.intro"
        : mode === "animation"
          ? "spriteAnimation.intro"
          : "spriteGeneration.intro",
    { name },
  );

  return (
    <>
      <SpriteGenerationPageFrame
        busy={Boolean(busy)}
        characterName={name}
        onClose={close}
        title={t("spriteGeneration.action")}
        modeTabs={
          <SegmentedTabs
            variant="pills"
            className="sprite-generation__mode-tabs"
            idPrefix={tabsId}
            ariaLabel={t("spriteAnimation.mode")}
            value={mode}
            onChange={(value) => {
              setMode(value);
            }}
            items={[
              { id: "static", label: t("spriteAnimation.staticTab") },
              { id: "animation", label: t("spriteAnimation.animationTab") },
              { id: "transition", label: t("spriteTransition.tab") },
              { id: "mouth", label: t("spriteMouth.tab") },
            ]}
          />
        }
        headerActions={
          <>
            <Select
              aria-label={t("spriteGeneration.previewSize")}
              value={previewSize}
              onChange={(event) => setPreviewSize(event.target.value)}
            >
              <option value="standard">{t("spriteGeneration.previewStandard")}</option>
              <option value="large">{t("spriteGeneration.previewLarge")}</option>
            </Select>
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
          </>
        }
        footer={
          mode === "mouth" ? (
            <>
              <div className="sprite-generation__selection" role="status">
                <strong>{t("spriteGeneration.selected", { count: mouths.selected.length })}</strong>
                <span>{t("spriteMouth.saveHint")}</span>
              </div>
              <AsyncButton
                variant="primary"
                disabled={Boolean(busy) || !mouths.selected.length}
                loading={mouths.busy === "save"}
                onClick={() => void mouths.save()}
              >
                {t("spriteMouth.save", { count: mouths.selected.length })}
              </AsyncButton>
            </>
          ) : (
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
                {t(mode === "transition" ? "spriteTransition.save" : "spriteGeneration.add", {
                  count: selected.length,
                })}
              </AsyncButton>
            </>
          )
        }
      >
        <div className="sprite-generation__journey">
          <ol className="sprite-generation__steps" aria-label={t("spriteGeneration.stepsLabel")}>
            {steps.map((step, index) => (
              <li
                key={step}
                aria-current={index === currentStep ? "step" : undefined}
                data-complete={index < currentStep}
              >
                <span className="sprite-generation__step-number" aria-hidden>
                  {index < currentStep ? <Check size={11} /> : index + 1}
                </span>
                {t(step)}
              </li>
            ))}
          </ol>
          <p className="sprite-generation__hint sprite-generation__intro" title={introText}>
            {introText}
          </p>
        </div>
        {mode === "mouth" ? (
          <div
            role="tabpanel"
            id={`${tabsId}-panel-mouth`}
            aria-labelledby={`${tabsId}-mouth`}
            className="sprite-transitions__panel"
            {...previewProps}
          >
            <SpriteMouthWorkspace character={character} controller={mouths} />
          </div>
        ) : mode === "transition" ? (
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
              onPreview={setMediaPreview}
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
                  onPreview={setMediaPreview}
                  busy={Boolean(busy)}
                  loading={busy === "animate"}
                  remaining={remaining}
                  hasItems={hasItems}
                />
              ) : (
                <SpriteStaticSettings
                  busy={Boolean(busy)}
                  characterSetting={character.character_setting}
                  count={count}
                  existingReferences={existingReferences}
                  h3Resolution={h3Resolution}
                  hasItems={hasItems}
                  mattingOptions={mattingOptions}
                  onCountChange={setCount}
                  onH3ResolutionChange={setH3Resolution}
                  onMattingChange={(value) => setAnimationInput((current) => ({ ...current, ...value }))}
                  onPlan={() => void generator.plan(count, requirements, reference)}
                  onPreview={setMediaPreview}
                  onReferenceChange={setReference}
                  onRemoveBackgroundChange={setRemoveBackground}
                  onRequirementsChange={setRequirements}
                  planning={busy === "plan"}
                  reference={reference}
                  remaining={remaining}
                  removeBackground={removeBackground}
                  replacementTags={replacementTags}
                  requirements={requirements}
                  validCount={validCount}
                />
              )}
            </aside>
            <SpriteGenerationWorkspace
              animationInputs={animationInputs}
              animationPending={animationPending}
              animationSelection={animationSelection}
              animationSourceMode={animationSourceMode}
              animationSources={animationSources}
              animationSourcesOpen={animationSourcesOpen}
              busy={busy}
              characterSprites={character.sprites}
              generator={generator}
              guideOpen={guideOpen}
              hasItems={hasItems}
              items={items}
              mode={mode}
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
              onAnimationSelectionChange={setAnimationSelection}
              onAnimationSourcesOpenChange={setAnimationSourcesOpen}
              onGuideOpenChange={setGuideOpen}
              onPreview={setMediaPreview}
              onReplace={(item) => {
                const original = item.original;
                const source = item.animationInput?.referenceImage || reference;
                const index =
                  original && character.sprites[original.index]?.path === original.path
                    ? original.index
                    : character.sprites.findIndex((sprite) => sprite.path === source);
                setReplacementIndex(index >= 0 ? String(index) : "");
                generator.clearError();
                setReplacementCandidate(item);
              }}
              pending={pending}
              reference={reference}
              remaining={remaining}
              removeBackground={removeBackground}
              renderable={renderable}
              selectable={selectable}
              selected={selectedSprites}
            />
          </div>
        )}
      </SpriteGenerationPageFrame>
      <MediaPreviewDialog
        media={mediaPreview}
        closeLabel={t("common.close")}
        backgroundColor={coloredPreview ? previewColor : undefined}
        onClose={() => setMediaPreview(null)}
      />
      <SpriteReplaceDialog
        busy={Boolean(busy)}
        candidate={replacementCandidate}
        error={generator.error}
        onClose={() => setReplacementCandidate(null)}
        onConfirm={async (candidate, targetIndex, targetPath) => {
          if (await generator.replace(candidate, targetIndex, targetPath)) {
            setReplacementCandidate(null);
          }
        }}
        onReplacementIndexChange={setReplacementIndex}
        previewProps={previewProps}
        replacementIndex={replacementIndex}
        replacementTags={replacementTags}
        replacing={busy === "replace"}
        sprites={character.sprites}
      />
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
