import { useMemo, useState } from "react";

import { fileUrl } from "../../entities/files/repository";
import { tagContents } from "../../shared/assets/assetText";
import {
  SPRITE_TRANSITION_PLAYBACK_RATE,
  SPRITE_TRANSITION_FRAME_COUNT,
  SPRITE_TRANSITION_FPS,
} from "../../shared/assets/spriteTransition";
import { useI18n } from "../../shared/i18n";
import type { Character, SpriteMattingOptions } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, NumberInput, Switch, TaskProgress, VisualMedia } from "../../shared/ui";
import { SpriteAnimationSourcePicker } from "./SpriteAnimationSourcePicker";
import { SpriteGenerationSetupGuide } from "./SpriteGenerationSetupGuide";
import { SpriteTransitionRecommendations } from "./SpriteTransitionRecommendations";
import { SpriteMattingStatus } from "./SpriteMattingStatus";
import { SpriteMattingSettings } from "./SpriteMattingSettings";
import { transitionPairs, type SpriteTransitionController } from "./useSpriteTransitions";

export function SpriteTransitionWorkspace({
  character,
  controller,
  mattingOptions,
  onMattingChange,
}: {
  character: Character;
  controller: SpriteTransitionController;
  mattingOptions: SpriteMattingOptions;
  onMattingChange: (value: SpriteMattingOptions) => void;
}) {
  const { t } = useI18n();
  const { sourceSelection: selection, setSourceSelection: setSelection } = controller;
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [guideOpen, setGuideOpen] = useState(false);
  const tags = tagContents(character.emotion_tags, character.sprites.length);
  const sources = character.sprites.map((sprite, index) => ({
    id: sprite.path,
    referenceImage: sprite.path,
    tagging: tags[index],
    index,
    origin: "existing" as const,
  }));
  const selectedPaths = sources.filter((source) => selection.includes(source.id)).map((source) => source.id);
  const manualPairs = useMemo(() => transitionPairs(selectedPaths), [selectedPaths.join("\n")]);
  const recommended = controller.planningMode === "recommended";
  const pairs = recommended ? controller.recommendedPairs : manualPairs;
  const sourceCount = recommended
    ? new Set(pairs.flatMap((pair) => [pair.fromPath, pair.toPath])).size
    : selectedPaths.length;
  const ready = controller.items.filter((item) => item.result?.alphaVerified);
  const selectable = ready.filter((item) => !item.saved && item.result?.frameCount === SPRITE_TRANSITION_FRAME_COUNT);
  const pending = pairs.filter(
    (pair) =>
      !controller.items.some(
        (item) =>
          item.id === pair.id &&
          item.result?.alphaVerified &&
          item.result.frameCount === SPRITE_TRANSITION_FRAME_COUNT &&
          !item.error,
      ),
  );
  const label = (path: string) => {
    const index = character.sprites.findIndex((sprite) => sprite.path === path);
    return `${t("spriteGeneration.sprite", { n: index + 1 })}${tags[index] ? ` · ${tags[index]}` : ""}`;
  };
  const busy = Boolean(controller.busy);

  return (
    <div className="sprite-generation__layout sprite-transitions">
      <aside className="sprite-generation__settings">
        <h3 className="sprite-generation__section-title">{t("spriteTransition.options")}</h3>
        <div className="sprite-generation__settings-fields">
          <div className="sprite-transitions__analysis-controls">
            <AsyncButton
              disabled={busy || sources.length < 2}
              loading={controller.busy === "transition-analyze"}
              onClick={() => void controller.analyze()}
            >
              {t("spriteTransition.analyze")}
            </AsyncButton>
            <p className="sprite-generation__hint">{t("spriteTransition.analyzeHint")}</p>
            <label className="sprite-generation__count">
              <span>{t("spriteTransition.recommendationCount")}</span>
              <NumberInput
                min={1}
                step={1}
                disabled={busy}
                value={controller.recommendationCount}
                onChange={(event) => controller.setRecommendationCount(event.target.value)}
              />
            </label>
            <Switch
              checked={controller.skipExisting}
              disabled={busy}
              onChange={(event) => controller.setSkipExisting(event.target.checked)}
            >
              {t("spriteTransition.skipExisting")}
            </Switch>
          </div>
          {controller.analysis ? (
            <div className="sprite-generation__toolbar" role="group" aria-label={t("spriteTransition.pairMode")}>
              <Button
                disabled={busy}
                aria-pressed={recommended}
                variant={recommended ? "primary" : "default"}
                onClick={() => controller.setPlanningMode("recommended")}
              >
                {t("spriteTransition.recommendations")}
              </Button>
              <Button
                disabled={busy}
                aria-pressed={!recommended}
                variant={!recommended ? "primary" : "default"}
                onClick={() => {
                  controller.setPlanningMode("manual");
                  setSourcesOpen(true);
                }}
              >
                {t("spriteTransition.manual")}
              </Button>
            </div>
          ) : null}
          <p className="sprite-generation__hint">
            {t(recommended ? "spriteTransition.recommendationHint" : "spriteTransition.directionHint")}
          </p>
          <p className="sprite-generation__hint">{t("spriteTransition.reuseHint")}</p>
          <SpriteMattingSettings value={mattingOptions} onChange={onMattingChange} disabled={busy} />
          <div className="sprite-transitions__instructions">
            <h4>{t("spriteTransition.playbackTitle")}</h4>
            <p className="sprite-generation__hint">{t("spriteTransition.playbackHint")}</p>
          </div>
        </div>
        <div className="sprite-generation__plan-action sprite-transitions__generate">
          <div className="sprite-transitions__summary" role="status">
            <strong>{t("spriteTransition.pairCount", { count: pairs.length, selected: sourceCount })}</strong>
            <span>
              {t("spriteTransition.spec", {
                frames: SPRITE_TRANSITION_FRAME_COUNT,
                duration: Number(
                  (SPRITE_TRANSITION_FRAME_COUNT / SPRITE_TRANSITION_FPS / SPRITE_TRANSITION_PLAYBACK_RATE).toFixed(2),
                ),
              })}
            </span>
          </div>
          <AsyncButton
            variant="primary"
            disabled={busy || pairs.length === 0}
            loading={controller.busy === "transition-generate"}
            onClick={() => {
              const batch = pairs.map((pair) => controller.items.find((item) => item.id === pair.id) ?? pair);
              void controller.generate(batch);
              setSourcesOpen(false);
            }}
          >
            {t("spriteTransition.generate", { count: pending.length || pairs.length })}
          </AsyncButton>
        </div>
      </aside>
      <section className="sprite-generation__workspace" aria-label={t("spriteTransition.tab")}>
        <div className="sprite-generation__workspace-header">
          <div>
            <h3 className="sprite-generation__section-title">{t("spriteTransition.results")}</h3>
            <p className="sprite-generation__hint">{t("spriteTransition.ready", { count: ready.length })}</p>
          </div>
          <div className="sprite-generation__toolbar">
            <Button
              variant="ghost"
              disabled={busy}
              aria-expanded={!recommended && sourcesOpen}
              onClick={() => {
                controller.setPlanningMode("manual");
                setSourcesOpen(recommended || !sourcesOpen);
              }}
            >
              {t("spriteAnimation.chooseSources")}
            </Button>
            <Button variant="ghost" aria-expanded={guideOpen} onClick={() => setGuideOpen(!guideOpen)}>
              {t("spriteGeneration.resources")}
            </Button>
            <Button
              variant="ghost"
              disabled={busy || !selectable.length}
              onClick={() => {
                const allSelected = selectable.every((item) => item.selected);
                selectable.forEach((item) => controller.update(item.id, { selected: !allSelected }));
              }}
            >
              {t(controller.selected.length ? "spriteTransition.deselectAll" : "spriteTransition.selectAll")}
            </Button>
          </div>
        </div>
        <div className="sprite-generation__feedback">
          {controller.error ? (
            <p className="sprite-generation__error" role="alert">
              {controller.error}
            </p>
          ) : null}
          {controller.busy === "transition-analyze" ? (
            <div className="sprite-generation__progress" aria-live="polite">
              <strong>{t("spriteTransition.analyzing")}</strong>
              {controller.task ? <TaskProgress compact logLimit={0} task={controller.task} /> : null}
            </div>
          ) : null}
          {controller.busy === "transition-generate" ? (
            <div className="sprite-generation__progress" aria-live="polite">
              <strong className="sprite-generation__queue-count">
                {t("spriteTransition.queue", controller.queue)}
              </strong>
              {controller.task ? (
                <TaskProgress compact logLimit={0} task={controller.task} />
              ) : (
                <span className="sprite-generation__working">{t("spriteGeneration.working")}</span>
              )}
              <Button disabled={controller.stopping} onClick={controller.stop}>
                {t(controller.stopping ? "spriteGeneration.stopping" : "spriteTransition.stop")}
              </Button>
            </div>
          ) : null}
        </div>
        <div className="sprite-generation__workspace-body">
          {recommended ? <SpriteTransitionRecommendations controller={controller} label={label} /> : null}
          {!recommended && sourcesOpen ? (
            <SpriteAnimationSourcePicker
              sources={sources}
              selectedSources={selection}
              onSourceSelectionChange={setSelection}
              busy={busy}
              remaining={sources.length}
              title={t("spriteTransition.pickSources")}
              hint={t("spriteTransition.sourceHint")}
              untaggedLabel={t("spriteTransition.untagged")}
              emptyHint={t("spriteTransition.noSources")}
            />
          ) : null}
          {guideOpen ? <SpriteGenerationSetupGuide /> : null}
          {controller.items.length ? (
            <div className="sprite-generation__grid">
              {controller.items.map((item) => (
                <article className="sprite-generation__card sprite-transitions__card" key={item.id}>
                  <label className="sprite-transitions__card-title">
                    <input
                      type="checkbox"
                      checked={Boolean(item.selected)}
                      disabled={
                        busy ||
                        item.saved ||
                        !item.result?.alphaVerified ||
                        item.result.frameCount !== SPRITE_TRANSITION_FRAME_COUNT
                      }
                      onChange={(event) => controller.update(item.id, { selected: event.target.checked })}
                    />
                    <strong>
                      {label(item.fromPath)} → {label(item.toPath)}
                    </strong>
                  </label>
                  <div className="sprite-transitions__preview">
                    {item.result ? (
                      <VisualMedia
                        alt={`${label(item.fromPath)} → ${label(item.toPath)}`}
                        loading="lazy"
                        playbackRate={SPRITE_TRANSITION_PLAYBACK_RATE}
                        src={fileUrl(item.result.path)}
                      />
                    ) : (
                      <div className="sprite-transitions__anchors">
                        <VisualMedia alt={label(item.fromPath)} autoPlay={false} src={fileUrl(item.fromPath)} />
                        <span>→</span>
                        <VisualMedia alt={label(item.toPath)} autoPlay={false} src={fileUrl(item.toPath)} />
                      </div>
                    )}
                  </div>
                  <p className="sprite-generation__hint">
                    {t(
                      item.saved
                        ? "spriteTransition.saved"
                        : item.result?.alphaVerified
                          ? "spriteTransition.transparent"
                          : "spriteTransition.pending",
                      { frames: item.result?.frameCount ?? 5 },
                    )}
                  </p>
                  <SpriteMattingStatus matting={item.result?.matting} />
                  {item.error || item.result?.backgroundRemovalError ? (
                    <p role="alert" className="sprite-generation__error">
                      {item.error || item.result?.backgroundRemovalError}
                    </p>
                  ) : null}
                  <div className="sprite-generation__toolbar">
                    {item.result && (!item.result.alphaVerified || (item.result.videoPath && item.result.taskId)) ? (
                      <Button
                        disabled={busy}
                        title={t("spriteMatting.retryHint")}
                        onClick={() => void controller.generate([item], false, true)}
                      >
                        {t(item.result.alphaVerified ? "spriteMatting.refineAgain" : "spriteAnimation.retryMatting")}
                      </Button>
                    ) : null}
                    <Button disabled={busy} onClick={() => void controller.generate([item], true)}>
                      {t(item.result ? "spriteTransition.redraw" : "spriteTransition.render")}
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          ) : !sourcesOpen && !recommended ? (
            <EmptyState title={t("spriteTransition.emptyTitle")} body={t("spriteTransition.sourceHint")} />
          ) : null}
        </div>
      </section>
    </div>
  );
}
