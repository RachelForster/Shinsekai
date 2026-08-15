import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import {
  cancelStoryGeneration,
  importGeneratedStoryProject,
  regenerateStoryGeneration,
  resumeStoryGeneration,
  startStoryGeneration,
} from "../../entities/story/repository";
import type { StoryGenerationStage, StoryGenerationTask } from "../../entities/story/types";
import { useI18n } from "../../shared/i18n";
import type { MessageKey } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import { MentionTextArea, characterMentionOptions } from "../../shared/ui";
import "./StoryGeneratorPage.css";

const stages: StoryGenerationStage[] = [
  "requirements",
  "bible",
  "characters",
  "state",
  "narrative",
  "logic",
  "resources",
];

const stageLabelKeys: Record<StoryGenerationStage, MessageKey> = {
  bible: "story.generator.stage.bible",
  characters: "story.generator.stage.characters",
  logic: "story.generator.stage.logic",
  narrative: "story.generator.stage.narrative",
  requirements: "story.generator.stage.requirements",
  resources: "story.generator.stage.resources",
  state: "story.generator.stage.state",
};

function taskFromUpdate(update: TaskSnapshot<StoryGenerationTask>) {
  return update.generationTask ?? update.result ?? null;
}

export function StoryGeneratorPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const mentionOptions = useMemo(
    () => characterMentionOptions(charactersQuery.data ?? [], t("mention.user")),
    [charactersQuery.data, t],
  );
  const [synopsis, setSynopsis] = useState("");
  const [task, setTask] = useState<StoryGenerationTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [regenerationStage, setRegenerationStage] = useState<StoryGenerationStage>("narrative");
  const taskRef = useRef<StoryGenerationTask | null>(null);
  const completed = useMemo(() => new Set(task?.completedStages ?? []), [task?.completedStages]);

  const rememberTask = (next: StoryGenerationTask) => {
    taskRef.current = next;
    setTask(next);
  };

  const track = (update: TaskSnapshot<StoryGenerationTask>) => {
    const next = taskFromUpdate(update);
    if (next) rememberTask(next);
  };

  const displayError = (() => {
    if (!error) return "";
    const code = task?.error?.code;
    if (code === "generation.validation_failed" || /did not pass validation after bounded repair/i.test(error)) {
      return t("story.generator.validationRepairFailed");
    }
    return error;
  })();
  const canOpenDraft = Boolean(task?.draftPath);

  const run = async (operation: () => Promise<StoryGenerationTask>, autoResume = true) => {
    setBusy(true);
    setError("");
    try {
      rememberTask(await operation());
    } catch (reason) {
      const current = taskRef.current;
      if (autoResume && current?.status === "failed") {
        try {
          rememberTask(await resumeStoryGeneration(current.id, { onTaskUpdate: track }));
          return;
        } catch (resumeReason) {
          setError(resumeReason instanceof Error ? resumeReason.message : String(resumeReason));
          return;
        }
      }
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const start = () =>
    run(() =>
      startStoryGeneration(
        { synopsis, options: { controlMode: "deterministic", targetLength: "short" } },
        { onTaskUpdate: track },
      ),
    );
  const resume = () => task && run(() => resumeStoryGeneration(task.id, { onTaskUpdate: track }), false);
  const regenerate = () =>
    task && run(() => regenerateStoryGeneration(task.id, regenerationStage, { onTaskUpdate: track }));
  const cancel = async () => {
    if (!task) return;
    try {
      setTask(await cancelStoryGeneration(task.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  const openEditor = async () => {
    if (!task) return;
    setBusy(true);
    setError("");
    try {
      const project = await importGeneratedStoryProject(task.id);
      navigate(`/settings/stories/${project.manifest.id}/edit`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="story-generator-page">
      <header className="story-generator-header">
        <div>
          <p className="story-generator-eyebrow">{t("story.generator.eyebrow")}</p>
          <h1>{t("story.generator.title")}</h1>
          <p>{t("story.generator.description")}</p>
        </div>
      </header>

      <section className="story-generator-card" aria-labelledby="story-synopsis-title">
        <h2 id="story-synopsis-title">{t("story.generator.synopsis")}</h2>
        <MentionTextArea
          aria-label={t("story.generator.synopsis")}
          disabled={busy}
          maxLength={20000}
          onChange={setSynopsis}
          options={mentionOptions}
          placeholder={t("story.generator.placeholder")}
          rows={8}
          value={synopsis}
        />
        <div className="story-generator-actions">
          <button disabled={busy || !synopsis.trim()} onClick={start} type="button">
            {busy ? t("story.generator.generating") : t("story.generator.start")}
          </button>
          {task?.status === "failed" || task?.status === "cancelled" ? (
            <button disabled={busy} onClick={resume} type="button">
              {t("story.generator.resume")}
            </button>
          ) : null}
          {task?.status === "running" ? (
            <button className="secondary" onClick={cancel} type="button">
              {t("story.generator.cancel")}
            </button>
          ) : null}
        </div>
        {displayError ? (
          <p className="story-generator-error" role="alert">
            {displayError}
          </p>
        ) : null}
      </section>

      {task ? (
        <>
          <section className="story-generator-card" aria-labelledby="story-progress-title">
            <div className="story-generator-section-heading">
              <div>
                <h2 id="story-progress-title">{t("story.generator.progress")}</h2>
                <p>
                  {t("story.generator.progressMeta", {
                    status: task.status,
                    stage: task.currentStage,
                  })}
                </p>
              </div>
              <code>{task.id}</code>
            </div>
            <ol className="story-generator-stages">
              {stages.map((stage) => (
                <li
                  className={completed.has(stage) ? "completed" : task.currentStage === stage ? "active" : ""}
                  key={stage}
                >
                  <span aria-hidden>{completed.has(stage) ? "✓" : "·"}</span>
                  {t(stageLabelKeys[stage])}
                </li>
              ))}
            </ol>
          </section>

          <section className="story-generator-grid">
            <article className="story-generator-card">
              <h2>{t("story.generator.assumptions")}</h2>
              {task.assumptions.length ? (
                <ul>
                  {task.assumptions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>{t("story.generator.assumptionsEmpty")}</p>
              )}
            </article>
            <article className="story-generator-card">
              <h2>{t("story.generator.validation")}</h2>
              {task.validation ? (
                <>
                  <p className={task.validation.valid ? "story-generator-pass" : "story-generator-error"}>
                    {t(task.validation.valid ? "story.generator.validationPassed" : "story.generator.validationFailed")}
                  </p>
                  <dl className="story-generator-metrics">
                    <div>
                      <dt>{t("story.generator.endingCoverage")}</dt>
                      <dd>{Math.round(task.validation.endingCoverage * 100)}%</dd>
                    </div>
                    <div>
                      <dt>{t("story.generator.exploredStates")}</dt>
                      <dd>{task.validation.exploredStates}</dd>
                    </div>
                    <div>
                      <dt>{t("story.generator.castFailures")}</dt>
                      <dd>{task.validation.castFailureNodeIds.length}</dd>
                    </div>
                    <div>
                      <dt>{t("story.generator.estimatedTokens")}</dt>
                      <dd>{task.cost.estimatedTokens}</dd>
                    </div>
                  </dl>
                  {task.validation.issues.length ? (
                    <ul>
                      {task.validation.issues.map((issue) => (
                        <li key={`${issue.code}-${issue.path}`}>
                          {issue.code}: {issue.message}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : (
                <p>{t("story.generator.validationEmpty")}</p>
              )}
            </article>
          </section>

          {task.status === "succeeded" ? (
            <section className="story-generator-card story-generator-regenerate">
              <div>
                <h2>{t("story.generator.regenerateTitle")}</h2>
                <p>{t("story.generator.regenerateHint")}</p>
              </div>
              <select
                aria-label={t("story.generator.regenerateStage")}
                onChange={(event) => setRegenerationStage(event.target.value as StoryGenerationStage)}
                value={regenerationStage}
              >
                {stages.map((stage) => (
                  <option key={stage} value={stage}>
                    {t(stageLabelKeys[stage])}
                  </option>
                ))}
              </select>
              <button disabled={busy} onClick={regenerate} type="button">
                {t("story.generator.regenerate")}
              </button>
              <button disabled={busy} onClick={openEditor} type="button">
                {t("story.generator.openEditor")}
              </button>
            </section>
          ) : canOpenDraft ? (
            <section className="story-generator-card story-generator-regenerate">
              <div>
                <h2>{t("story.generator.openEditor")}</h2>
                <p>{t("story.generator.openDraftHint")}</p>
              </div>
              <button disabled={busy} onClick={openEditor} type="button">
                {t("story.generator.openEditor")}
              </button>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
