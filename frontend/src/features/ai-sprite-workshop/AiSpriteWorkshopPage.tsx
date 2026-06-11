import { useEffect, useMemo, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";
import { Eraser, ImagePlus, RefreshCw, Sparkles, WandSparkles } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  charactersQueryKey,
  listCharacters,
  registerGeneratedCharacterSprites,
} from "../../entities/character/repository";
import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import { generateSpriteImage, generateSpritePrompts, removeSpriteBackground } from "../../entities/tools/repository";
import { fileUrl } from "../../entities/files/repository";
import type { Character } from "../../entities/config/types";
import { isT2iReadyForSprites } from "../api-settings/apiSettingsUtils";
import { useI18n } from "../../shared/i18n";
import type { FrontendLanguage } from "../../shared/i18n";
import type { SpritePromptItem } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  EmptyState,
  NumberInput,
  QueryErrorState,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import "./AiSpriteWorkshopPage.css";

interface SpritePromptDraft {
  id: string;
  imagePath?: string;
  imageVersion?: number;
  label: string;
  prompt: string;
  status: "added" | "draft" | "failed" | "ready";
  index: number;
}

const TAG_PRESETS: Record<FrontendLanguage, string[]> = {
  en: [
    "neutral, relaxed pose",
    "smile, hand near chest",
    "serious, upright pose",
    "surprised, hand gesture",
    "sad, lowered shoulders",
    "determined, dramatic pose",
    "playful, body turn",
    "calm, elegant pose",
  ],
  ja: [
    "\u901a\u5e38, \u30ea\u30e9\u30c3\u30af\u30b9\u7acb\u3061",
    "\u7b11\u9854, \u80f8\u306b\u624b",
    "\u771f\u5263, \u59ff\u52e2\u826f\u304f",
    "\u9a5a\u304d, \u624b\u632f\u308a",
    "\u60b2\u3057\u307f, \u80a9\u3092\u843d\u3068\u3059",
    "\u6c7a\u610f, \u5287\u7684\u306a\u7acb\u3061",
    "\u904a\u3073\u5fc3, \u4f53\u3092\u3072\u306d\u308b",
    "\u7a4f\u3084\u304b, \u4e0a\u54c1\u306a\u7acb\u3061",
  ],
  zh_CN: [
    "\u9ed8\u8ba4, \u653e\u677e\u7ad9\u59ff",
    "\u5fae\u7b11, \u624b\u653e\u80f8\u524d",
    "\u4e25\u8083, \u633a\u76f4\u7ad9\u59ff",
    "\u60ca\u8bb6, \u624b\u52bf",
    "\u96be\u8fc7, \u5782\u80a9",
    "\u575a\u5b9a, \u620f\u5267\u6027\u7ad9\u59ff",
    "\u4fcf\u76ae, \u8f6c\u8eab",
    "\u5e73\u9759, \u4f18\u96c5\u7ad9\u59ff",
  ],
};

function selectedCharacter(characters: Character[], selectedName: string) {
  return characters.find((character) => character.name === selectedName) ?? characters[0] ?? null;
}

function normalizeSpriteCount(value: number) {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.min(12, Math.max(1, Math.round(value)));
}

function spriteLabelSeed(language: FrontendLanguage, index: number) {
  const presets = TAG_PRESETS[language] ?? TAG_PRESETS.zh_CN;
  return presets[index % presets.length];
}

function englishPromptText(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[^\x20-\x7E]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function versionedImageUrl(path: string, version?: number) {
  const url = fileUrl(path);
  if (!url || !version || /^(?:blob:|data:)/.test(url)) {
    return url;
  }
  return `${url}${url.includes("?") ? "&" : "?"}v=${version}`;
}

function splitPromptLine(value: string): SpritePromptItem {
  const text = value.trim();
  const match = text.match(/^(?:\d+[.)]\s*)?([^:：|]+)[:：|]\s*(.+)$/);
  if (match) {
    return {
      label: match[1].trim(),
      prompt: englishPromptText(match[2]),
    };
  }
  return {
    label: "",
    prompt: englishPromptText(text),
  };
}

function buildDraftsFromLlmItems(
  language: FrontendLanguage,
  items: SpritePromptItem[],
): SpritePromptDraft[] {
  return items
    .map<SpritePromptDraft | null>((item, index) => {
      const prompt = englishPromptText(item.prompt || "");
      if (!prompt) {
        return null;
      }
      return {
        id: `sprite-${index + 1}`,
        index,
        label: item.label?.trim() || spriteLabelSeed(language, index),
        prompt,
        status: "draft" as const,
      };
    })
    .filter((item): item is SpritePromptDraft => item !== null);
}

export function AiSpriteWorkshopPage() {
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const characters = charactersQuery.data ?? [];
  const [selectedName, setSelectedName] = useState(() => searchParams.get("character") ?? "");
  const [spriteCount, setSpriteCount] = useState(4);
  const character = useMemo(() => selectedCharacter(characters, selectedName), [characters, selectedName]);
  const [drafts, setDrafts] = useState<SpritePromptDraft[]>([]);
  const [generatingIds, setGeneratingIds] = useState<Set<string>>(() => new Set());
  const [bgRemovingIds, setBgRemovingIds] = useState<Set<string>>(() => new Set());
  const [composition, setComposition] = useState("thigh_up");
  const [positivePromptReference, setPositivePromptReference] = useState("");
  const [negativePrompt, setNegativePrompt] = useState(
    "low quality, blurry, extra limbs, text, watermark, multiple views, multiple angles, turnaround, character sheet, reference sheet, expression sheet, pose sheet, multiple panels, collage",
  );
  const [generationNote, setGenerationNote] = useState("");
  const t2iReady = configQuery.data ? isT2iReadyForSprites(configQuery.data.api_config) : false;
  const llmProvider = configQuery.data?.api_config.llm_provider ?? "";
  const t2iProvider = configQuery.data?.api_config.t2i_provider ?? "";
  const readyDrafts = drafts.filter((draft) => draft.status === "ready" && draft.imagePath);
  const hasReadyDraft = readyDrafts.length > 0;
  const isGeneratingImages = generatingIds.size > 0;
  const promptReferenceInput = positivePromptReference.trim();

  const promptMutation = useMutation({
    mutationFn: () =>
      generateSpritePrompts({
        characterName: character?.name ?? "",
        composition,
        count: normalizeSpriteCount(spriteCount),
        language,
        ...(promptReferenceInput ? { positivePromptReference: promptReferenceInput } : {}),
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("tools.msgNoPrompts"),
        title: t("tools.msgTitlePrompts"),
      });
    },
    onSuccess(result) {
      if (!character) {
        return;
      }
      const items = result.items?.length
        ? result.items
        : result.prompts.map((prompt) => splitPromptLine(prompt));
      const nextDrafts = buildDraftsFromLlmItems(language, items);
      setDrafts(nextDrafts);
      setGenerationNote(t("aiSprites.promptGenerated", { count: nextDrafts.length }));
    },
  });

  useEffect(() => {
    if (!selectedName && characters[0]) {
      setSelectedName(characters[0].name);
    }
  }, [characters, selectedName]);

  useEffect(() => {
    setDrafts([]);
    setGenerationNote("");
  }, [character?.name, composition, language, promptReferenceInput, spriteCount]);

  const updateDraft = (id: string, patch: Partial<SpritePromptDraft>) => {
    setDrafts((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const setDraftGenerating = (id: string, generating: boolean) => {
    setGeneratingIds((current) => {
      const next = new Set(current);
      if (generating) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  };

  const refreshPrompts = () => {
    if (!character) {
      return;
    }
    promptMutation.mutate();
  };

  const refreshOnePrompt = async (draft: SpritePromptDraft) => {
    if (!character) {
      return;
    }
    try {
      const result = await generateSpritePrompts({
        characterName: character.name,
        composition,
        count: 1,
        language,
        ...(promptReferenceInput ? { positivePromptReference: promptReferenceInput } : {}),
      });
      const items = result.items?.length ? result.items : result.prompts.map((prompt) => splitPromptLine(prompt));
      const [next] = buildDraftsFromLlmItems(language, items);
      if (!next) {
        throw new Error(t("tools.msgNoPrompts"));
      }
      updateDraft(draft.id, { label: next.label, prompt: next.prompt, status: "draft" });
      setGenerationNote(t("aiSprites.promptRefreshed"));
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("tools.msgNoPrompts"),
        title: t("tools.msgTitlePrompts"),
      });
    }
  };

  const generateOneSprite = async (draft: SpritePromptDraft) => {
    if (!character) {
      return;
    }
    setDraftGenerating(draft.id, true);
    updateDraft(draft.id, { status: "draft" });
    try {
      const result = await generateSpriteImage(
        {
          characterName: character.name,
          label: draft.label,
          negativePrompt,
          prompt: draft.prompt,
        },
        {
          onTaskUpdate(task) {
            if (task.message) {
              setGenerationNote(task.message);
            }
          },
        },
      );
      const imagePath = result.file ?? result.files[0] ?? "";
      if (!imagePath) {
        throw new Error(t("aiSprites.imageFailed"));
      }
      updateDraft(draft.id, { imagePath, imageVersion: Date.now(), status: "ready" });
      setGenerationNote(result.message || t("aiSprites.imageGenerated"));
    } catch (error) {
      updateDraft(draft.id, { status: "failed" });
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("aiSprites.imageFailed"),
        title: t("aiSprites.imageTitle"),
      });
    } finally {
      setDraftGenerating(draft.id, false);
    }
  };

  const removeBgForReady = async () => {
    const filePaths = readyDrafts.map((d) => d.imagePath).filter(Boolean) as string[];
    if (!filePaths.length) {
      showToast({ kind: "error", message: t("tools.rmbgFirst"), title: t("tools.rmbgTitle") });
      return;
    }
    setBgRemovingIds(new Set(readyDrafts.map((d) => d.id)));
    try {
      const result = await removeSpriteBackground(
        { files: filePaths, inputDir: filePaths[0].split("/").slice(0, -1).join("/") },
        {
          onTaskUpdate(task) {
            if (task.message) {
              setGenerationNote(task.message);
            }
          },
        },
      );
      setGenerationNote(result.message);
      showToast({ kind: "success", message: result.message, title: t("tools.rmbgTitle") });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("common.operationFailed"),
        title: t("tools.rmbgTitle"),
      });
    } finally {
      setBgRemovingIds(new Set());
    }
  };

  const generateAllSprites = async () => {
    for (const draft of drafts) {
      await generateOneSprite(draft);
    }
  };

  const registerSpritesMutation = useMutation({
    mutationFn: () => {
      if (!character) {
        throw new Error(t("character.emptyTitle"));
      }
      return registerGeneratedCharacterSprites({
        items: readyDrafts.map((draft) => ({
          label: draft.label,
          path: draft.imagePath ?? "",
        })),
        name: character.name,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("aiSprites.addToCharacter"),
      });
    },
    onSuccess(savedCharacter) {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current) =>
        current?.map((item) => (item.name === savedCharacter.name ? savedCharacter : item)) ?? current,
      );
      void queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      const addedPaths = new Set(readyDrafts.map((draft) => draft.imagePath).filter(Boolean));
      setDrafts((current) =>
        current.map((draft) => (draft.imagePath && addedPaths.has(draft.imagePath) ? { ...draft, status: "added" } : draft)),
      );
      setGenerationNote(t("aiSprites.addedToCharacter", { count: addedPaths.size }));
      showToast({
        kind: "success",
        message: t("aiSprites.addedToCharacter", { count: addedPaths.size }),
        title: t("aiSprites.addToCharacter"),
      });
    },
  });

  if (configQuery.isError) {
    return (
      <QueryErrorState
        body={t("api.error.saveFallback")}
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (charactersQuery.isError) {
    return (
      <QueryErrorState
        body={t("character.error.saveFallback")}
        error={charactersQuery.error}
        onRetry={() => void charactersQuery.refetch()}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (configQuery.isLoading || charactersQuery.isLoading) {
    return <EmptyState title={t("aiSprites.loading")} />;
  }

  if (!t2iReady) {
    return (
      <div className="page ai-sprite-page">
        <EmptyState
          action={
            <NavLink className="button button--primary" to="/settings/api">
              <span className="button__label">{t("aiSprites.configureT2i")}</span>
            </NavLink>
          }
          body={t("aiSprites.notReadyBody")}
          title={t("aiSprites.notReadyTitle")}
        />
      </div>
    );
  }

  return (
    <div className="page ai-sprite-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("aiSprites.title")}</h1>
          <p className="page__description">{t("aiSprites.description")}</p>
        </div>
      </header>

      <section className="section ai-sprite-page__setup">
        <div className="ai-sprite-page__summary">
          <div>
            <span>{t("aiSprites.llm")}</span>
            <strong>{llmProvider || "-"}</strong>
          </div>
          <div>
            <span>{t("aiSprites.t2i")}</span>
            <strong>{t2iProvider || "-"}</strong>
          </div>
        </div>
        <div className="form-grid form-grid--two">
          <label className="field-row">
            <span className="field-row__label">{t("tools.character")}</span>
            <span className="field-row__control">
              <Select
                disabled={!characters.length}
                onChange={(event) => setSelectedName(event.target.value)}
                value={character?.name ?? ""}
              >
                {characters.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("aiSprites.spriteCount")}</span>
            <span className="field-row__control">
              <NumberInput
                max={12}
                min={1}
                onChange={(event) => setSpriteCount(normalizeSpriteCount(Number(event.target.value)))}
                step={1}
                value={spriteCount}
              />
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("aiSprites.composition")}</span>
            <span className="field-row__control">
              <Select onChange={(event) => setComposition(event.target.value)} value={composition}>
                <option value="thigh_up">{t("aiSprites.composition.thighUp")}</option>
                <option value="upper_body">{t("aiSprites.composition.upperBody")}</option>
                <option value="full_body">{t("aiSprites.composition.fullBody")}</option>
              </Select>
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("aiSprites.positivePromptReference")}</span>
            <span className="field-row__control">
              <TextArea
                onChange={(event) => setPositivePromptReference(event.target.value)}
                placeholder={t("aiSprites.positivePromptReferencePlaceholder")}
                rows={3}
                value={positivePromptReference}
              />
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("aiSprites.negativePrompt")}</span>
            <span className="field-row__control">
              <TextInput onChange={(event) => setNegativePrompt(event.target.value)} value={negativePrompt} />
            </span>
          </label>
        </div>
      </section>

      <section className="section">
        <div className="section__header">
          <div>
            <h2 className="section__title">{t("aiSprites.promptDrafts")}</h2>
            <p className="section__description">{t("aiSprites.promptDraftsHint")}</p>
          </div>
          <AsyncButton
            disabled={!character || promptMutation.isPending}
            icon={<WandSparkles aria-hidden className="button__icon" />}
            onClick={refreshPrompts}
          >
            {t("aiSprites.generatePrompts")}
          </AsyncButton>
        </div>

        {!characters.length ? <EmptyState title={t("character.emptyTitle")} body={t("character.emptyBody")} /> : null}
        {characters.length && !drafts.length ? (
          <EmptyState title={t("aiSprites.promptEmptyTitle")} body={t("aiSprites.promptEmptyBody")} />
        ) : null}
        {drafts.length ? (
          <div className="ai-sprite-page__prompt-grid">
            {drafts.map((draft) => (
              <article className="ai-sprite-card" key={draft.id}>
                <div className="ai-sprite-card__header">
                  <div>
                    <h3>{t("aiSprites.promptCandidate", { n: draft.index + 1 })}</h3>
                    <span>{t("aiSprites.sdPrompt")}</span>
                  </div>
                  <Button
                    icon={<RefreshCw aria-hidden className="button__icon" />}
                    onClick={() => void refreshOnePrompt(draft)}
                    tooltip={t("aiSprites.retryOne")}
                    variant="ghost"
                  >
                    {t("aiSprites.retry")}
                  </Button>
                </div>
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("aiSprites.spriteTag")}</span>
                  <span className="field-row__control">
                    <TextInput
                      onChange={(event) => updateDraft(draft.id, { label: event.target.value })}
                      value={draft.label}
                    />
                  </span>
                </label>
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("aiSprites.sdPrompt")}</span>
                  <span className="field-row__control">
                    <TextArea
                      className="ai-sprite-card__prompt"
                      onChange={(event) => updateDraft(draft.id, { prompt: event.target.value })}
                      value={draft.prompt}
                    />
                  </span>
                </label>
                <div className="ai-sprite-card__preview" data-status={draft.status}>
                  {draft.imagePath ? (
                    <img
                      alt={draft.label || t("aiSprites.promptCandidate", { n: draft.index + 1 })}
                      src={versionedImageUrl(draft.imagePath, draft.imageVersion)}
                    />
                  ) : (
                    <>
                      <ImagePlus aria-hidden className="ai-sprite-card__icon" />
                      <span>{t("aiSprites.candidatePlaceholder")}</span>
                    </>
                  )}
                </div>
                <Button
                  loading={generatingIds.has(draft.id)}
                  onClick={() => void generateOneSprite(draft)}
                  variant={draft.imagePath ? "default" : "primary"}
                >
                  {draft.imagePath ? t("aiSprites.retryImage") : t("aiSprites.generateImage")}
                </Button>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      <section className="section ai-sprite-page__actions">
        <AsyncButton
          disabled={!drafts.length || isGeneratingImages}
          icon={<Sparkles aria-hidden className="button__icon" />}
          loading={isGeneratingImages}
          onClick={() => void generateAllSprites()}
          variant="primary"
        >
          {t("aiSprites.generateAllImages")}
        </AsyncButton>
        <AsyncButton
          disabled={!hasReadyDraft || registerSpritesMutation.isPending}
          loading={registerSpritesMutation.isPending}
          onClick={() => registerSpritesMutation.mutate()}
        >
          {t("aiSprites.addToCharacter")}
        </AsyncButton>
        <AsyncButton
          disabled={!hasReadyDraft || bgRemovingIds.size > 0}
          icon={<Eraser aria-hidden className="button__icon" />}
          loading={bgRemovingIds.size > 0}
          onClick={() => void removeBgForReady()}
          variant="ghost"
        >
          {t("aiSprites.removeBackground")}
        </AsyncButton>
        <p>{generationNote || t("aiSprites.safeSaveHint")}</p>
      </section>
    </div>
  );
}
