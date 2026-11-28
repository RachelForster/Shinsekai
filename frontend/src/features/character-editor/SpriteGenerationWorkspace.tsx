import { useRef } from "react";
import { Plus } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { Character, CharacterSpriteAnimationInput } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, TaskProgress, type MediaPreview } from "../../shared/ui";
import { SpriteAnimationSourcePicker } from "./SpriteAnimationSourcePicker";
import type { SpriteAnimationSource } from "./spriteAnimationSources";
import { SpriteCandidateCard } from "./SpriteCandidateCard";
import { SpriteGenerationSetupGuide } from "./SpriteGenerationSetupGuide";
import type { SpriteCandidate, useSpriteGeneration } from "./useSpriteGeneration";

interface SpriteGenerationWorkspaceProps {
  animationInputs: CharacterSpriteAnimationInput[];
  animationPending: SpriteCandidate[];
  animationSelection: string[];
  animationSourceMode: "library" | "file";
  animationSources: SpriteAnimationSource[];
  animationSourcesOpen: boolean;
  busy: string | boolean | null | undefined;
  characterSprites: Character["sprites"];
  generator: ReturnType<typeof useSpriteGeneration>;
  guideOpen: boolean;
  hasItems: boolean;
  items: SpriteCandidate[];
  mode: "static" | "animation";
  onAnimate: (item: SpriteCandidate) => void;
  onAnimationSelectionChange: (selection: string[]) => void;
  onAnimationSourcesOpenChange: (open: boolean) => void;
  onGuideOpenChange: (open: boolean) => void;
  onPreview: (media: MediaPreview) => void;
  onReplace: (item: SpriteCandidate) => void;
  pending: SpriteCandidate[];
  reference: string;
  remaining: number;
  removeBackground: boolean;
  renderable: SpriteCandidate[];
  selectable: SpriteCandidate[];
  selected: SpriteCandidate[];
}

export function SpriteGenerationWorkspace({
  animationInputs,
  animationPending,
  animationSelection,
  animationSourceMode,
  animationSources,
  animationSourcesOpen,
  busy,
  characterSprites,
  generator,
  guideOpen,
  hasItems,
  items,
  mode,
  onAnimate,
  onAnimationSelectionChange,
  onAnimationSourcesOpenChange,
  onGuideOpenChange,
  onPreview,
  onReplace,
  pending,
  reference,
  remaining,
  removeBackground,
  renderable,
  selectable,
  selected,
}: SpriteGenerationWorkspaceProps) {
  const { t } = useI18n();
  const workspaceBodyRef = useRef<HTMLDivElement>(null);

  return (
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
              onGuideOpenChange(false);
              onAnimationSourcesOpenChange(false);
            }}
          >
            {t("spriteGeneration.manualSingle")}
          </Button>
          {mode === "animation" && animationSourceMode === "library" ? (
            <Button
              variant="ghost"
              aria-expanded={animationSourcesOpen}
              onClick={() => {
                onAnimationSourcesOpenChange(!animationSourcesOpen);
                if (workspaceBodyRef.current) workspaceBodyRef.current.scrollTop = 0;
              }}
            >
              {t("spriteAnimation.chooseSources")}
            </Button>
          ) : null}
          <Button
            aria-expanded={guideOpen}
            onClick={() => {
              onGuideOpenChange(!guideOpen);
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
            onSourceSelectionChange={onAnimationSelectionChange}
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
                  onPreview={onPreview}
                  onReplace={characterSprites.length ? onReplace : undefined}
                  onAnimate={onAnimate}
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
  );
}
