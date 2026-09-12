import { useI18n } from "../../shared/i18n";
import { Button, Select } from "../../shared/ui";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SegmentedTabs } from "../../shared/ui/SegmentedTabs";
import { StoryLibrary } from "./components/StoryLibrary";
import type { StoryGenerationStage } from "../../entities/story/types";
import { StoryFeatureGate } from "./components/StoryFeatureGate";
import { StorySetupForm } from "./components/StorySetupForm";
import { GenerationStages } from "./components/GenerationStages";
import { GenerationValidation } from "./components/GenerationValidation";
import { StoryLaunchButton } from "./components/StoryLaunchButton";
import { StoryGraphView } from "./graph/StoryGraphView";
import { useStoryGeneration } from "./state/useStoryGeneration";
import { stages } from "./state/stages";
import "./StoryGeneratorPage.css";

function StoryWorkspace() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const [view, setView] = useState<"create" | "library">(() =>
    params.get("view") === "library" ? "library" : "create",
  );
  const generation = useStoryGeneration();
  const [regenerationStage, setRegenerationStage] = useState<StoryGenerationStage>("narrative");
  const { task, pending, preview } = generation;
  return (
    <>
      <SegmentedTabs
        ariaLabel={t("story.entry")}
        idPrefix="story-view"
        value={view}
        onChange={setView}
        items={[
          { id: "create", label: t("story.create") },
          { id: "library", label: t("story.library") },
        ]}
      />
      <div
        role="tabpanel"
        id="story-view-panel-library"
        aria-labelledby="story-view-library"
        hidden={view !== "library"}
      >
        {view === "library" && <StoryLibrary onCreate={() => setView("create")} />}
      </div>
      <div role="tabpanel" id="story-view-panel-create" aria-labelledby="story-view-create" hidden={view !== "create"}>
        <StorySetupForm pending={pending} onStart={generation.start} />
        {generation.error && (
          <p className="story-generator-error" role="alert">
            {generation.error}
          </p>
        )}
        {task && (
          <>
            <GenerationStages task={task} preview={preview} />
            <div className="story-generator-actions">
              {pending && (
                <Button type="button" disabled={task.cancelRequested} onClick={() => void generation.cancel()}>
                  {task.cancelRequested ? t("story.cancelling") : t("story.cancel")}
                </Button>
              )}
            </div>
            {preview?.graph && <StoryGraphView graph={preview.graph} />}
            <GenerationValidation task={task} />
            {task.status === "succeeded" && (
              <section className="section">
                <h2 className="section__title">{preview?.title || t("story.generated")}</h2>
                <p className="section__description">{t("story.savedHint")}</p>
                <StoryLaunchButton
                  key={`${task.id}-${task.updatedAt}`}
                  storyPath={task.draftPath}
                  disabled={pending || !task.validation?.valid || !task.draftPath}
                />
                <details className="story-regenerate">
                  <summary>{t("story.regenerate.title")}</summary>
                  <p className="section__description">{t("story.regenerate.hint")}</p>
                  <div className="story-generator-actions">
                    <Select
                      aria-label={t("story.regenerate.stage")}
                      value={regenerationStage}
                      disabled={pending}
                      onChange={(event) => setRegenerationStage(event.target.value as StoryGenerationStage)}
                    >
                      {stages.map((stage) => (
                        <option key={stage.id} value={stage.id}>
                          {t(stage.label)}
                        </option>
                      ))}
                    </Select>
                    <Button
                      disabled={pending}
                      type="button"
                      onClick={() => void generation.regenerate(regenerationStage)}
                    >
                      {t("story.regenerate.action")}
                    </Button>
                  </div>
                </details>
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}

export function StoryGeneratorPage() {
  const { t } = useI18n();
  return (
    <div className="page story-generator-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("story.title")}</h1>
          <p className="section__description">{t("story.description")}</p>
        </div>
      </header>
      <StoryFeatureGate>
        <StoryWorkspace />
      </StoryFeatureGate>
    </div>
  );
}
