import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { Button, VisualMedia } from "../../shared/ui";
import { transitionKey, type SpriteTransitionController } from "./useSpriteTransitions";

export function SpriteTransitionRecommendations({
  controller,
  label,
}: {
  controller: SpriteTransitionController;
  label: (path: string) => string;
}) {
  const { t } = useI18n();
  const analysis = controller.analysis;
  if (!analysis) return null;
  const selected = new Set(controller.recommendedPairs.map((item) => item.id));
  const coverage = analysis.items
    .filter((item) => selected.has(transitionKey(item.fromPath, item.toPath)))
    .reduce((total, item) => total + item.probability, 0);
  const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
  return (
    <section
      className="sprite-generation__source-picker sprite-transitions__recommendations"
      aria-label={t("spriteTransition.recommendations")}
    >
      <div className="sprite-generation__source-header">
        <h4>{t("spriteTransition.recommendations")}</h4>
        <Button disabled={Boolean(controller.busy) || !analysis.items.length} onClick={controller.chooseTop}>
          {t("spriteTransition.chooseTop", { count: controller.recommendationCount || 0 })}
        </Button>
      </div>
      <p className="sprite-generation__hint">
        {t("spriteTransition.analysisSummary", {
          dialogs: analysis.dialogCount,
          mapped: analysis.mappedDialogCount,
          sessions: analysis.conversationCount,
          changes: analysis.transitionCount,
        })}
        {" · "}
        {t(analysis.basis === "inferred" ? "spriteTransition.inferredBasis" : "spriteTransition.instructionsBasis", {
          count: analysis.inferredDialogCount,
        })}
      </p>
      {analysis.items.length ? (
        <>
          <p className="sprite-generation__source-count" role="status">
            {t("spriteTransition.coverage", { count: selected.size, coverage: percent(coverage) })}
          </p>
          <div className="sprite-transitions__ranking-scroll">
            <table className="sprite-transitions__ranking">
              <thead>
                <tr>
                  <th>{t("spriteTransition.directedPair")}</th>
                  <th>{t("spriteTransition.share")}</th>
                  <th>{t("spriteTransition.conditional")}</th>
                  <th>{t("spriteTransition.occurrences")}</th>
                </tr>
              </thead>
              <tbody>
                {analysis.items.map((item, index) => {
                  const id = transitionKey(item.fromPath, item.toPath);
                  const title = `${label(item.fromPath)} → ${label(item.toPath)}`;
                  const existing = controller.isReady(item.fromPath, item.toPath);
                  return (
                    <tr key={id} data-selected={selected.has(id)}>
                      <td>
                        <label className="sprite-transitions__rank-pair">
                          <input
                            type="checkbox"
                            checked={selected.has(id)}
                            aria-label={title}
                            disabled={Boolean(controller.busy) || (controller.skipExisting && existing)}
                            onChange={() => controller.toggleRecommendation(id)}
                          />
                          <span className="sprite-transitions__rank-number">{index + 1}</span>
                          <span className="sprite-transitions__rank-thumbnails" aria-hidden="true">
                            <VisualMedia alt="" src={fileUrl(item.fromPath)} autoPlay={false} loading="lazy" />
                            <span>→</span>
                            <VisualMedia alt="" src={fileUrl(item.toPath)} autoPlay={false} loading="lazy" />
                          </span>
                          <span>
                            {title}
                            {existing ? <small>{t("spriteTransition.alreadyAvailable")}</small> : null}
                          </span>
                        </label>
                      </td>
                      <td>{percent(item.probability)}</td>
                      <td>{percent(item.conditionalProbability)}</td>
                      <td>{item.count}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="sprite-generation__hint">{t("spriteTransition.probabilityHint")}</p>
        </>
      ) : (
        <p className="sprite-generation__notice">{t("spriteTransition.noChanges")}</p>
      )}
    </section>
  );
}
