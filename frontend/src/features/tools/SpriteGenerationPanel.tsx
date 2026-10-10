import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, RotateCcw, WandSparkles } from "lucide-react";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { generateSpritePrompts, generateSprites } from "../../entities/tools/repository";
import { fileUrl } from "../../entities/files/repository";
import { baseName } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import type { SpriteGenerationRequest, SpriteGenerationResult, TaskSnapshot } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  Dialog,
  EmptyState,
  FilePicker,
  NumberInput,
  QueryErrorState,
  Select,
  Switch,
  TaskProgress,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import "./ToolsPage.css";

function extractPrompt(line: string) {
  const trimmed = line.trim();
  if (!trimmed) {
    return "";
  }
  const match = trimmed.match(/^(?:sprite|立绘|立ち絵)\s*\d+\s*[:：]\s*(.+)$/i);
  return (match?.[1] ?? trimmed).trim();
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
    <img alt={baseName(file)} className="tool-gallery__thumb" onError={() => setFailed(true)} src={fileUrl(file)} />
  );
}

interface SpriteGenerationPanelProps {
  fixedCharacterName?: string;
  initialReferenceImages?: string[];
  onImportGenerated?: (files: string[], tags: string[]) => Promise<void>;
  onBusyChange?: (busy: boolean) => void;
  dialog?: { open: boolean; onClose: () => void };
}

interface GeneratedSprite {
  id: string;
  file: string;
  prompt: string;
  request: SpriteGenerationRequest;
  tags: string;
  labelError?: string;
  imported: boolean;
}

function generatedSprites(result: SpriteGenerationResult, request: SpriteGenerationRequest): GeneratedSprite[] {
  return result.files.map((file, index) => ({
    id: file,
    file,
    prompt: request.prompts[index],
    request: { ...request, outputDir: result.outputDir },
    tags: result.labels?.[index] ?? "",
    labelError: result.labelErrors?.find((error) => error.index === index)?.message,
    imported: false,
  }));
}

export function SpriteGenerationPanel({
  fixedCharacterName,
  initialReferenceImages = [],
  onImportGenerated,
  onBusyChange,
  dialog,
}: SpriteGenerationPanelProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const charactersQuery = useQuery({
    queryFn: listCharacters,
    queryKey: charactersQueryKey,
    enabled: !fixedCharacterName,
  });
  const characters = fixedCharacterName ? [{ name: fixedCharacterName }] : (charactersQuery.data ?? []);
  const isLoading = !fixedCharacterName && charactersQuery.isLoading;
  const [selectedCharacter, setSelectedCharacter] = useState(fixedCharacterName ?? "");
  const [spriteCount, setSpriteCount] = useState(1);
  const [referenceImages, setReferenceImages] = useState(initialReferenceImages.length ? initialReferenceImages : [""]);
  const [imageProvider, setImageProvider] = useState<"configured" | "gemini">("configured");
  const [promptText, setPromptText] = useState("");
  const [spriteOutputDir, setSpriteOutputDir] = useState("");
  const [sprites, setSprites] = useState<GeneratedSprite[]>([]);
  const [autoLabel, setAutoLabel] = useState(true);
  const [toolOutput, setToolOutput] = useState("");
  const [toolTask, setToolTask] = useState<TaskSnapshot<unknown> | null>(null);
  const imported = sprites.length > 0 && sprites.every((sprite) => sprite.imported);

  useEffect(() => {
    if (!selectedCharacter && characters[0]) {
      setSelectedCharacter(characters[0].name);
    }
  }, [characters, selectedCharacter]);

  const prompts = useMemo(() => promptText.split("\n").map(extractPrompt).filter(Boolean), [promptText]);
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
    mutationFn: (request: SpriteGenerationRequest) =>
      generateSprites(request, { onTaskUpdate: (task) => setToolTask(task) }),
    onError(error) {
      showOperationError(error, t("tools.msgTitleGen"), t("tools.msgGenFailed"));
    },
    onMutate() {
      setToolTask(null);
    },
    onSuccess(result, request) {
      setSprites(generatedSprites(result, request));
      setToolOutput(result.message || t("tools.msgGenOk", { dir: result.outputDir, n: result.files.length }));
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: async (sprite: GeneratedSprite) => {
      const result = await generateSprites(
        {
          ...sprite.request,
          autoLabel,
          prompts: [sprite.prompt],
          seed: Math.floor(Math.random() * 2 ** 32),
        },
        { onTaskUpdate: (task) => setToolTask(task) },
      );
      if (!result.files.length) throw new Error(t("tools.msgGenFailed"));
      return result;
    },
    onMutate() {
      setToolTask(null);
    },
    onError(error) {
      showOperationError(error, t("tools.regenerate"), t("tools.msgGenFailed"));
    },
    onSuccess(result, sprite) {
      const [updated] = generatedSprites(result, { ...sprite.request, prompts: [sprite.prompt] });
      setSprites((current) => current.map((item) => (item.id === sprite.id ? { ...updated, id: item.id } : item)));
      setToolOutput(result.message || t("tools.msgGenOk", { dir: result.outputDir, n: result.files.length }));
    },
  });

  const importMutation = useMutation({
    mutationFn: async (items: GeneratedSprite[]) => {
      await onImportGenerated?.(
        items.map((item) => item.file),
        items.map((item) => item.tags.trim()),
      );
    },
    onSuccess(_result, items) {
      const files = new Set(items.map((item) => item.file));
      setSprites((current) => current.map((item) => (files.has(item.file) ? { ...item, imported: true } : item)));
    },
    onError(error) {
      showOperationError(error, t("character.sprite.uploadImages"), t("character.sprite.imageError"));
    },
  });
  const busy =
    promptMutation.isPending || spriteMutation.isPending || regenerateMutation.isPending || importMutation.isPending;
  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  const startPromptGeneration = () => {
    if (busy) return;
    if (!selectedCharacter) {
      showToast({ kind: "error", title: t("tools.msgTitlePrompts"), message: t("tools.msgSelectChar") });
      return;
    }
    promptMutation.mutate();
  };

  const startSpriteGeneration = () => {
    if (busy) return;
    if (!selectedCharacter) {
      showToast({ kind: "error", title: t("tools.msgTitleGen"), message: t("tools.msgSelectChar") });
      return;
    }
    if (!referenceImages.some((path) => path.trim())) {
      showToast({ kind: "error", title: t("tools.msgTitleGen"), message: t("tools.msgRefInvalid") });
      return;
    }
    if (!prompts.length) {
      showToast({ kind: "error", title: t("tools.msgTitleGen"), message: t("tools.msgNoPrompts") });
      return;
    }
    spriteMutation.mutate({
      autoLabel,
      characterName: selectedCharacter,
      outputDir: spriteOutputDir.trim() || undefined,
      prompts: [...prompts],
      provider: imageProvider,
      referenceImages: referenceImages.map((path) => path.trim()).filter(Boolean),
    });
  };

  const content = (
    <>
      <div className="tool-group">
        <div className="section__header">
          <div>
            <h3 className="section__title">{t("tools.gemBox")}</h3>
            <p className="section__description">{t("tools.gemHint")}</p>
          </div>
        </div>

        {!fixedCharacterName && charactersQuery.isError ? (
          <QueryErrorState
            error={charactersQuery.error}
            onRetry={() => void charactersQuery.refetch()}
            retryLabel={t("common.retry")}
            title={t("common.operationFailed")}
          />
        ) : null}

        <div className="tools-grid tools-grid--two">
          <div className="form-grid">
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("tools.character")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("tools.character")}
                  disabled={Boolean(fixedCharacterName) || isLoading || !characters.length}
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
              disabled={
                !characters.length ||
                spriteMutation.isPending ||
                regenerateMutation.isPending ||
                importMutation.isPending
              }
              icon={<WandSparkles aria-hidden className="button__icon" />}
              loading={promptMutation.isPending}
              onClick={startPromptGeneration}
            >
              {t("tools.genPromptsBtn")}
            </AsyncButton>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("tools.imageProvider")}</span>
              <Select
                aria-label={t("tools.imageProvider")}
                onChange={(event) => setImageProvider(event.target.value as "configured" | "gemini")}
                value={imageProvider}
              >
                <option value="configured">{t("tools.configuredT2i")}</option>
                <option value="gemini">Gemini</option>
              </Select>
            </label>
            {referenceImages.map((path, index) => {
              const setPath = (value: string) =>
                setReferenceImages((current) => current.map((item, i) => (i === index ? value : item)));
              return (
                <div className="field-row field-row--stack" key={index}>
                  <label>
                    <span className="field-row__label">
                      {t("tools.refLabel")} {index + 1}
                    </span>
                    <FilePicker
                      acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                      onChange={(event) => setPath(event.target.value)}
                      onPathChange={setPath}
                      pickLabel={t("tools.browse")}
                      pickerTitle={t("tools.refDialogTitle")}
                      placeholder={t("tools.refPlaceholder")}
                      value={path}
                    />
                  </label>
                  {referenceImages.length > 1 ? (
                    <Button
                      onClick={() => setReferenceImages((current) => current.filter((_, i) => i !== index))}
                      variant="ghost"
                    >
                      {t("tools.removeReference", { n: index + 1 })}
                    </Button>
                  ) : null}
                </div>
              );
            })}
            <Button
              disabled={referenceImages.length >= 10}
              onClick={() => setReferenceImages((current) => [...current, ""])}
              variant="ghost"
            >
              {t("tools.addReference")}
            </Button>
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
            <Switch checked={autoLabel} disabled={busy} onChange={(event) => setAutoLabel(event.target.checked)}>
              {t("tools.autoLabel")}
            </Switch>
            <p className="section__description">{t("tools.autoLabelHint")}</p>
            <AsyncButton
              icon={<ImageIcon aria-hidden className="button__icon" />}
              disabled={promptMutation.isPending || regenerateMutation.isPending || importMutation.isPending}
              loading={spriteMutation.isPending}
              onClick={startSpriteGeneration}
              variant="primary"
            >
              {t("tools.genSpritesBtn")}
            </AsyncButton>
          </div>
        </div>

        <div className="tool-gallery" aria-label={t("tools.galleryLabel")}>
          <div className="tool-gallery__header">
            <div className="tool-gallery__title">{t("tools.galleryLabel")}</div>
            {onImportGenerated && sprites.length ? (
              <AsyncButton
                disabled={
                  imported || promptMutation.isPending || spriteMutation.isPending || regenerateMutation.isPending
                }
                loading={importMutation.isPending}
                onClick={() => importMutation.mutate(sprites.filter((sprite) => !sprite.imported))}
              >
                {imported
                  ? t("character.sprite.generatedImported")
                  : t("character.sprite.importGenerated", { name: selectedCharacter })}
              </AsyncButton>
            ) : null}
          </div>
          {!sprites.length ? <EmptyState title={t("tools.galleryEmpty")} /> : null}
          {sprites.length ? (
            <div className="tool-gallery__items">
              {sprites.map((sprite, index) => (
                <div className="tool-gallery__item" key={sprite.id} title={sprite.file}>
                  <AsyncButton
                    aria-label={t("tools.regenerateSprite", { n: index + 1 })}
                    disabled={busy && !(regenerateMutation.isPending && regenerateMutation.variables?.id === sprite.id)}
                    icon={<RotateCcw aria-hidden className="button__icon" />}
                    loading={regenerateMutation.isPending && regenerateMutation.variables?.id === sprite.id}
                    onClick={() => {
                      if (!busy) regenerateMutation.mutate(sprite);
                    }}
                  >
                    {t("tools.regenerate")}
                  </AsyncButton>
                  <GeneratedSpritePreview file={sprite.file} key={sprite.file} />
                  <div className="tool-gallery__details">
                    <strong>{baseName(sprite.file)}</strong>
                    <span title={sprite.prompt}>{sprite.prompt}</span>
                  </div>
                  <TextInput
                    aria-label={t("tools.spriteTags", { n: index + 1 })}
                    disabled={busy || sprite.imported}
                    onChange={(event) => {
                      const tags = event.target.value;
                      setSprites((current) =>
                        current.map((item) =>
                          item.id === sprite.id ? { ...item, tags, labelError: undefined } : item,
                        ),
                      );
                    }}
                    placeholder={t("tools.spriteTagsPlaceholder")}
                    value={sprite.tags}
                  />
                  {sprite.labelError ? (
                    <p className="tool-gallery__warning" role="status">
                      {sprite.labelError}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <TaskProgress logLimit={5} task={toolTask} />
      <TextArea className="tools-page__output" readOnly value={toolOutput} />
    </>
  );
  // Keep the task controller mounted while the dialog is closed.
  return dialog ? (
    <Dialog
      className="sprite-generation-dialog"
      closeLabel={t("common.close")}
      onClose={dialog.onClose}
      open={dialog.open}
      title={t("character.sprite.generateTitle", { name: fixedCharacterName ?? selectedCharacter })}
    >
      {content}
    </Dialog>
  ) : (
    content
  );
}
