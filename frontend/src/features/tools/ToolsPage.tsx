import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Eraser, Image as ImageIcon, Scissors, WandSparkles } from "lucide-react";

import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import {
  cropSprites,
  generateSpritePrompts,
  generateSprites,
  removeSpriteBackground,
} from "../../entities/tools/repository";
import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import {
  AsyncButton,
  EmptyState,
  FilePicker,
  NumberInput,
  QueryErrorState,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";

function extractPrompt(line: string) {
  const trimmed = line.trim();
  if (!trimmed) {
    return "";
  }
  const match = trimmed.match(/^[^:：]+[:：]\s*(.+)$/);
  return (match?.[1] ?? trimmed).trim();
}

function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function GeneratedSpritePreview({ file }: { file: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="tool-gallery__fallback" aria-hidden>
        <ImageIcon className="tool-gallery__icon" />
      </div>
    );
  }

  return (
    <img alt={basename(file)} className="tool-gallery__thumb" onError={() => setFailed(true)} src={fileUrl(file)} />
  );
}

export function ToolsPage() {
  const { t } = useI18n();
  const { showToast } = useToast();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const characters = charactersQuery.data ?? [];
  const isLoading = charactersQuery.isLoading;
  const [selectedCharacter, setSelectedCharacter] = useState("");
  const [spriteCount, setSpriteCount] = useState(1);
  const [referenceImage, setReferenceImage] = useState("");
  const [promptText, setPromptText] = useState("");
  const [spriteOutputDir, setSpriteOutputDir] = useState("");
  const [generatedFiles, setGeneratedFiles] = useState<string[]>([]);
  const [cropInputDir, setCropInputDir] = useState("");
  const [cropOutputDir, setCropOutputDir] = useState("");
  const [cropRatio, setCropRatio] = useState(1);
  const [rmbgInputDir, setRmbgInputDir] = useState("");
  const [rmbgOutputDir, setRmbgOutputDir] = useState("");
  const [toolOutput, setToolOutput] = useState("");
  const [toolTask, setToolTask] = useState<TaskSnapshot<unknown> | null>(null);

  useEffect(() => {
    if (!selectedCharacter && characters[0]) {
      setSelectedCharacter(characters[0].name);
    }
  }, [characters, selectedCharacter]);

  const prompts = useMemo(() => promptText.split("\n").map(extractPrompt).filter(Boolean), [promptText]);
  const taskProgress = toolTask?.progress == null ? null : Math.round(toolTask.progress * 100);
  const taskLogs = toolTask?.logs.slice(-5) ?? [];

  const showOperationError = (error: unknown, title: string, fallback: string) => {
    showToast({
      kind: "error",
      message: error instanceof Error ? error.message : fallback,
      title,
    });
  };

  const promptMutation = useMutation({
    mutationFn: () =>
      generateSpritePrompts(
        { characterName: selectedCharacter, count: spriteCount },
        { onTaskUpdate: (task) => setToolTask(task) },
      ),
    onError(error) {
      showOperationError(error, t("tools.msgTitlePrompts"), t("tools.msgNoPrompts"));
    },
    onMutate() {
      setToolTask(null);
    },
    onSuccess(result) {
      setPromptText(
        result.prompts.map((prompt, index) => t("tools.promptLine", { n: index + 1, text: prompt })).join("\n"),
      );
      setToolOutput(t("tools.promptsGenerated", { n: result.prompts.length }));
    },
  });

  const spriteMutation = useMutation({
    mutationFn: () =>
      generateSprites(
        {
          characterName: selectedCharacter,
          outputDir: spriteOutputDir.trim() || undefined,
          prompts,
          referenceImage: referenceImage.trim(),
        },
        { onTaskUpdate: (task) => setToolTask(task) },
      ),
    onError(error) {
      showOperationError(error, t("tools.msgTitleGen"), t("tools.msgGenFailed"));
    },
    onMutate() {
      setToolTask(null);
      setGeneratedFiles([]);
    },
    onSuccess(result) {
      setGeneratedFiles(result.files);
      setToolOutput(result.message || t("tools.msgGenOk", { dir: result.outputDir, n: result.files.length }));
    },
  });

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

  const startPromptGeneration = () => {
    if (!selectedCharacter) {
      showToast({ kind: "error", title: t("tools.msgTitlePrompts"), message: t("tools.msgSelectChar") });
      return;
    }
    promptMutation.mutate();
  };

  const startSpriteGeneration = () => {
    if (!selectedCharacter) {
      showToast({ kind: "error", title: t("tools.msgTitleGen"), message: t("tools.msgSelectChar") });
      return;
    }
    if (!referenceImage.trim()) {
      showToast({ kind: "error", title: t("tools.msgTitleGen"), message: t("tools.msgRefInvalid") });
      return;
    }
    if (!prompts.length) {
      showToast({ kind: "error", title: t("tools.msgTitleGen"), message: t("tools.msgNoPrompts") });
      return;
    }
    spriteMutation.mutate();
  };

  return (
    <div className="page tools-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("nav.tools")}</h1>
          <p className="page__description">{t("tools.description")}</p>
        </div>
      </header>

      <div aria-label={t("common.subpages")} className="segmented-tabs" role="tablist">
        <button aria-selected="true" className="segmented-tabs__tab" role="tab" type="button">
          {t("tools.tabMain")}
        </button>
      </div>

      <section className="section">
        <div className="section__header">
          <h2 className="section__title">{t("tools.h2Sprites")}</h2>
        </div>

        <div className="tool-group">
          <div className="section__header">
            <div>
              <h3 className="section__title">{t("tools.gemBox")}</h3>
              <p className="section__description">{t("tools.gemHint")}</p>
            </div>
          </div>

          {charactersQuery.isError ? (
            <QueryErrorState
              error={charactersQuery.error}
              onRetry={() => void charactersQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}

          <div className="tools-grid tools-grid--three">
            <div className="form-grid">
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.character")}</span>
                <span className="field-row__control">
                  <Select
                    disabled={isLoading || !characters.length}
                    onChange={(event) => setSelectedCharacter(event.target.value)}
                    value={selectedCharacter}
                  >
                    {characters.map((character) => (
                      <option key={character.name} value={character.name}>
                        {character.name}
                      </option>
                    ))}
                  </Select>
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.spriteCount")}</span>
                <span className="field-row__control">
                  <NumberInput
                    max={100}
                    min={1}
                    onChange={(event) => setSpriteCount(Number(event.target.value) || 1)}
                    step={1}
                    value={spriteCount}
                  />
                </span>
              </label>
              <AsyncButton
                disabled={!characters.length}
                icon={<WandSparkles aria-hidden className="button__icon" />}
                loading={promptMutation.isPending}
                onClick={startPromptGeneration}
              >
                {t("tools.genPromptsBtn")}
              </AsyncButton>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("tools.refLabel")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                    onChange={(event) => setReferenceImage(event.target.value)}
                    onPathChange={setReferenceImage}
                    pickLabel={t("tools.browse")}
                    pickerTitle={t("tools.refDialogTitle")}
                    placeholder={t("tools.refPlaceholder")}
                    value={referenceImage}
                  />
                </span>
              </label>
            </div>

            <div className="form-grid">
              <TextArea
                className="tools-page__prompts"
                onChange={(event) => setPromptText(event.target.value)}
                placeholder={t("tools.promptsPlaceholder")}
                value={promptText}
              />
              <TextInput
                onChange={(event) => setSpriteOutputDir(event.target.value)}
                placeholder={t("tools.outputDirPlaceholder")}
                value={spriteOutputDir}
              />
              <AsyncButton
                icon={<ImageIcon aria-hidden className="button__icon" />}
                loading={spriteMutation.isPending}
                onClick={startSpriteGeneration}
                variant="primary"
              >
                {t("tools.genSpritesBtn")}
              </AsyncButton>
            </div>

            <div className="tool-gallery" aria-label={t("tools.galleryLabel")}>
              <div className="tool-gallery__title">{t("tools.galleryLabel")}</div>
              {!generatedFiles.length ? <EmptyState title={t("tools.galleryEmpty")} /> : null}
              {generatedFiles.length ? (
                <div className="tool-gallery__items">
                  {generatedFiles.map((file) => (
                    <div className="tool-gallery__item" key={file} title={file}>
                      <GeneratedSpritePreview file={file} />
                      <div>
                        <strong>{basename(file)}</strong>
                        <span>{file}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </div>
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

      {toolTask ? (
        <div className="task-progress" role="status" aria-live="polite">
          <div className="task-progress__meta">
            <strong>{toolTask.phase}</strong>
            <span>{taskProgress == null ? toolTask.status : `${taskProgress}%`}</span>
          </div>
          {taskProgress == null ? null : (
            <div className="task-progress__track" aria-hidden>
              <span className="task-progress__fill" style={{ width: `${taskProgress}%` }} />
            </div>
          )}
          <div className="task-progress__message">{toolTask.message || toolTask.status}</div>
          {taskLogs.length ? <pre className="task-progress__log">{taskLogs.join("\n")}</pre> : null}
        </div>
      ) : null}

      <TextArea className="tools-page__output" readOnly value={toolOutput} />
    </div>
  );
}
