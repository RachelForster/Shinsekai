import { useI18n, type MessageKey } from "../../../shared/i18n";
import type { StoryGenerationTask } from "../../../entities/story/types";
import type { StoryGenerationPreview } from "../../../shared/platform/storyPreviewTypes";
import { stages, taskStatus } from "../state/stages";

const labels: Record<string, MessageKey> = {
  title: "story.artifact.title",
  premise: "story.artifact.premise",
  themes: "story.artifact.themes",
  worldRules: "story.artifact.worldRules",
  immutableFacts: "story.artifact.immutableFacts",
  secrets: "story.artifact.secrets",
  assumptions: "story.artifact.assumptions",
  characters: "story.artifact.characters",
  name: "story.artifact.name",
  responsibility: "story.artifact.responsibility",
  personality: "story.artifact.personality",
  description: "story.artifact.description",
  profile: "story.artifact.personality",
  setting: "story.artifact.setting",
  summary: "story.artifact.summary",
};

const recoveryLabels: Record<NonNullable<StoryGenerationTask["recovery"]>["state"], MessageKey> = {
  resuming: "story.recovery.resuming",
  working: "story.recovery.working",
  correcting: "story.recovery.correcting",
  waiting: "story.recovery.waiting",
};

function ArtifactContent({ value }: { value: unknown }) {
  const { t } = useI18n();
  if (Array.isArray(value))
    return (
      <ul>
        {value.map((item, index) => (
          <li key={index}>
            <ArtifactContent value={item} />
          </li>
        ))}
      </ul>
    );
  if (value && typeof value === "object")
    return (
      <dl className="story-artifact">
        {Object.entries(value)
          .filter(([key]) => key in labels)
          .map(([key, item]) => (
            <div key={key}>
              <dt>{t(labels[key])}</dt>
              <dd>
                <ArtifactContent value={item} />
              </dd>
            </div>
          ))}
      </dl>
    );
  return <span>{String(value ?? "")}</span>;
}

export function GenerationStages({ task, preview }: { task: StoryGenerationTask; preview?: StoryGenerationPreview }) {
  const { t, language } = useI18n();
  return (
    <section className="section" aria-labelledby="story-progress-title">
      <h2 className="section__title" id="story-progress-title">
        {t("story.progress.title")}
      </h2>
      <p className="section__description" role="status" aria-live="polite">
        {t(taskStatus[task.status])}
        {task.currentStage === "repair" ? t("story.progress.repairing") : ""}
      </p>
      {task.recovery && !task.cancelRequested && task.status === "running" && (
        <div className="section__description" role="status">
          <p>{t("story.recovery.hint", { status: t(recoveryLabels[task.recovery.state]) })}</p>
          {!!task.recovery.attempt && (
            <p>{t("story.recovery.attempts", { attempts: task.recovery.attempt, repairs: task.repairAttempts })}</p>
          )}
          {!!task.recovery.nextRetryAt && (
            <p>
              {t("story.recovery.nextRetry", {
                time: new Date(task.recovery.nextRetryAt).toLocaleTimeString(language.replace("_", "-")),
              })}
            </p>
          )}
          {task.recovery.lastError && (
            <details>
              <summary>{t("story.recovery.error")}</summary>
              <p>{task.recovery.lastError.message}</p>
            </details>
          )}
        </div>
      )}
      <ol className="story-generator-stages">
        {stages.map((stage) => {
          const completed = task.completedStages.includes(stage.id);
          const current = task.currentStage === stage.id;
          return (
            <li key={stage.id} className={completed ? "completed" : current ? "active" : ""}>
              <span aria-hidden>{completed ? "✓" : current ? "◉" : "○"}</span>
              {t(stage.label)}
              <small>
                {completed
                  ? t("story.stage.completed")
                  : current
                    ? t("story.stage.processing")
                    : t("story.stage.waiting")}
              </small>
            </li>
          );
        })}
      </ol>
      <div className="story-stage-artifacts">
        {stages.map((stage) => (
          <details key={stage.id}>
            <summary>
              {t(stage.label)}
              <small>{t(stage.description)}</small>
            </summary>
            {preview?.artifacts[stage.id] ? (
              <>
                {stage.id === "narrative" ? (
                  <p className="section__description">
                    {t("story.stage.nodes", { count: preview.graph?.nodes.length ?? 0 })}
                  </p>
                ) : (
                  <ArtifactContent value={preview.artifacts[stage.id]} />
                )}
                <details>
                  <summary>{t("story.stage.details")}</summary>
                  <pre>{JSON.stringify(preview.artifacts[stage.id], null, 2)}</pre>
                </details>
              </>
            ) : (
              <p className="section__description">
                {task.completedStages.includes(stage.id) ? t("story.stage.loading") : t("story.stage.pending")}
              </p>
            )}
          </details>
        ))}
      </div>
    </section>
  );
}
