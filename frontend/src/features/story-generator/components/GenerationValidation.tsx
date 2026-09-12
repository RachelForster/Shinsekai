import { useI18n } from "../../../shared/i18n";
import type { StoryGenerationTask } from "../../../entities/story/types";

export function GenerationValidation({ task }: { task: StoryGenerationTask }) {
  const { t } = useI18n();
  return (
    <section className="section" aria-labelledby="story-validation-title">
      <h2 className="section__title" id="story-validation-title">
        {t("story.validation.title")}
      </h2>
      {task.validation ? (
        <>
          <p className={task.validation.valid ? "story-generator-pass" : "story-generator-error"}>
            {task.validation.valid
              ? t("story.validation.passed")
              : task.cancelRequested || task.status === "cancelled"
                ? t("story.validation.stopped")
                : t("story.validation.repairing")}
          </p>
          <p className="section__description">
            {t("story.validation.metrics", {
              coverage: Math.round(task.validation.endingCoverage * 100),
              states: task.validation.exploredStates,
            })}
          </p>
          {!!task.validation.issues.length && (
            <ul>
              {task.validation.issues.map((issue, index) => (
                <li key={index}>{issue.message}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="section__description">{t("story.validation.hint")}</p>
      )}
      {!!task.assumptions.length && (
        <details>
          <summary>{t("story.artifact.assumptions")}</summary>
          <ul>
            {task.assumptions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
