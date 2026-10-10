import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Eraser, Scissors } from "lucide-react";
import { cropSprites, removeSpriteBackground } from "../../entities/tools/repository";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import { AsyncButton, NumberInput, TaskProgress, TextArea, TextInput, useToast } from "../../shared/ui";
import { SpriteGenerationPanel } from "./SpriteGenerationPanel";
import "./ToolsPage.css";

export function ToolsPanelContent({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [cropInputDir, setCropInputDir] = useState("");
  const [cropOutputDir, setCropOutputDir] = useState("");
  const [cropRatio, setCropRatio] = useState(1);
  const [rmbgInputDir, setRmbgInputDir] = useState("");
  const [rmbgOutputDir, setRmbgOutputDir] = useState("");
  const [toolOutput, setToolOutput] = useState("");
  const [toolTask, setToolTask] = useState<TaskSnapshot<unknown> | null>(null);

  const showOperationError = (error: unknown, title: string, fallback: string) => {
    showToast({
      kind: "error",
      message: error instanceof Error ? error.message : fallback,
      title,
    });
  };

  const cropMutation = useMutation({
    mutationFn: () =>
      cropSprites(
        { inputDir: cropInputDir.trim(), outputDir: cropOutputDir.trim() || undefined, ratio: cropRatio },
        { onTaskUpdate: (task) => setToolTask(task) },
      ),
    onError(error) {
      showOperationError(error, t("tools.cropTitle"), t("common.operationFailed"));
    },
    onMutate() {
      setToolTask(null);
    },
    onSuccess(result) {
      setToolOutput(result.message);
    },
  });

  const rmbgMutation = useMutation({
    mutationFn: () =>
      removeSpriteBackground(
        { inputDir: rmbgInputDir.trim(), outputDir: rmbgOutputDir.trim() || undefined },
        { onTaskUpdate: (task) => setToolTask(task) },
      ),
    onError(error) {
      showOperationError(error, t("tools.rmbgTitle"), t("common.operationFailed"));
    },
    onMutate() {
      setToolTask(null);
    },
    onSuccess(result) {
      setToolOutput(result.message);
    },
  });

  return (
    <div className={["page", "tools-page", embedded ? "tools-page--embedded" : ""].filter(Boolean).join(" ")}>
      {!embedded ? (
        <header className="page__header">
          <div>
            <h1 className="page__title">{t("nav.tools")}</h1>
          </div>
        </header>
      ) : null}

      <div aria-label={t("common.subpages")} className="segmented-tabs segmented-tabs--underline" role="tablist">
        <button aria-selected="true" className="segmented-tabs__tab" role="tab" type="button">
          {t("tools.tabMain")}
        </button>
      </div>

      <section className="section">
        <div className="section__header">
          <h2 className="section__title">{t("tools.h2Sprites")}</h2>
        </div>

        <SpriteGenerationPanel />
      </section>

      <section className="section">
        <div className="tools-grid tools-grid--two">
          <div className="tool-group">
            <div className="section__header">
              <h2 className="section__title">{t("tools.cropTitle")}</h2>
            </div>
            <div className="form-grid">
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.cropInput")}</span>
                <span className="field-row__control">
                  <TextInput onChange={(event) => setCropInputDir(event.target.value)} value={cropInputDir} />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.cropOutput")}</span>
                <span className="field-row__control">
                  <TextInput onChange={(event) => setCropOutputDir(event.target.value)} value={cropOutputDir} />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.cropRatio")}</span>
                <span className="field-row__control">
                  <NumberInput
                    max={1}
                    min={0}
                    onChange={(event) => {
                      const next = Number(event.target.value);
                      setCropRatio(Number.isFinite(next) ? next : 1);
                    }}
                    step={0.05}
                    value={cropRatio}
                  />
                </span>
              </label>
              <AsyncButton
                icon={<Scissors aria-hidden className="button__icon" />}
                loading={cropMutation.isPending}
                onClick={() => cropMutation.mutate()}
              >
                {t("tools.cropBtn")}
              </AsyncButton>
            </div>
          </div>

          <div className="tool-group">
            <div className="section__header">
              <div>
                <h2 className="section__title">{t("tools.rmbgTitle")}</h2>
                <p className="section__description">{t("tools.rmbgFirst")}</p>
              </div>
            </div>
            <div className="form-grid">
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.rmbgInput")}</span>
                <span className="field-row__control">
                  <TextInput onChange={(event) => setRmbgInputDir(event.target.value)} value={rmbgInputDir} />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.rmbgOutput")}</span>
                <span className="field-row__control">
                  <TextInput onChange={(event) => setRmbgOutputDir(event.target.value)} value={rmbgOutputDir} />
                </span>
              </label>
              <AsyncButton
                icon={<Eraser aria-hidden className="button__icon" />}
                loading={rmbgMutation.isPending}
                onClick={() => rmbgMutation.mutate()}
              >
                {t("tools.rmbgBtn")}
              </AsyncButton>
            </div>
          </div>
        </div>
      </section>

      <TaskProgress logLimit={5} task={toolTask} />

      <TextArea className="tools-page__output" readOnly value={toolOutput} />
    </div>
  );
}

export function ToolsPage() {
  return <ToolsPanelContent />;
}
