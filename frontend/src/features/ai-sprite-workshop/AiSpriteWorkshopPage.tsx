import { useEffect, useMemo, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";
import { ImagePlus, RefreshCw, Sparkles, WandSparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import type { Character } from "../../entities/config/types";
import { isT2iReadyForSprites } from "../api-settings/apiSettingsUtils";
import { useI18n } from "../../shared/i18n";
import type { FrontendLanguage } from "../../shared/i18n";
import {
  AsyncButton,
  Button,
  EmptyState,
  NumberInput,
  QueryErrorState,
  Select,
  TextArea,
  TextInput,
} from "../../shared/ui";
import "./AiSpriteWorkshopPage.css";

interface SpritePromptDraft {
  id: string;
  label: string;
  prompt: string;
  status: "draft" | "failed" | "ready";
  index: number;
}

const POSE_VARIATIONS = [
  "neutral expression, relaxed standing pose",
  "gentle smile, one hand near chest",
  "serious expression, confident upright pose",
  "surprised expression, dynamic hand gesture",
  "soft sad expression, slightly lowered shoulders",
  "determined expression, dramatic visual novel pose",
  "playful expression, light body turn",
  "calm expression, elegant standing pose",
] as const;

const TAG_PRESETS: Record<FrontendLanguage, string[]> = {
  en: ["Neutral", "Smile", "Serious", "Surprised", "Sad", "Determined", "Playful", "Calm"],
  ja: ["通常", "笑顔", "真剣", "驚き", "悲しみ", "決意", "遊び心", "穏やか"],
  zh_CN: ["默认", "微笑", "严肃", "惊讶", "难过", "坚定", "俏皮", "平静"],
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

function sdPromptSeed(character: Character, index: number) {
  const setting = character.character_setting.trim();
  const name = character.name.trim() || "character";
  const variation = POSE_VARIATIONS[index % POSE_VARIATIONS.length];
  return [
    "masterpiece",
    "best quality",
    "highres",
    "anime visual novel sprite",
    name,
    "single character sprite",
    "solo",
    "full body",
    "standing",
    "front view or three-quarter view",
    "transparent background",
    "clean lineart",
    "soft cel shading",
    "consistent character design",
    variation,
    `character name: ${name}`,
    setting ? `character personality and design: ${setting}` : "",
  ]
    .filter(Boolean)
    .join(", ");
}

function buildPromptDraft(character: Character, index: number, language: FrontendLanguage): SpritePromptDraft {
  return {
    id: `sprite-${index + 1}`,
    index,
    label: spriteLabelSeed(language, index),
    prompt: sdPromptSeed(character, index),
    status: "draft",
  };
}

function buildPromptDrafts(
  character: Character | null,
  count: number,
  language: FrontendLanguage,
): SpritePromptDraft[] {
  if (!character) {
    return [];
  }
  return Array.from({ length: normalizeSpriteCount(count) }, (_, index) =>
    buildPromptDraft(character, index, language),
  );
}

export function AiSpriteWorkshopPage() {
  const { language, t } = useI18n();
  const [searchParams] = useSearchParams();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const characters = charactersQuery.data ?? [];
  const [selectedName, setSelectedName] = useState(() => searchParams.get("character") ?? "");
  const [spriteCount, setSpriteCount] = useState(4);
  const character = useMemo(() => selectedCharacter(characters, selectedName), [characters, selectedName]);
  const [drafts, setDrafts] = useState<SpritePromptDraft[]>([]);
  const [negativePrompt, setNegativePrompt] = useState("low quality, blurry, extra limbs, text, watermark");
  const [generationNote, setGenerationNote] = useState("");
  const t2iReady = configQuery.data ? isT2iReadyForSprites(configQuery.data.api_config) : false;
  const llmProvider = configQuery.data?.api_config.llm_provider ?? "";
  const t2iProvider = configQuery.data?.api_config.t2i_provider ?? "";
  const hasReadyDraft = drafts.some((draft) => draft.status === "ready");

  useEffect(() => {
    if (!selectedName && characters[0]) {
      setSelectedName(characters[0].name);
    }
  }, [characters, selectedName]);

  useEffect(() => {
    setDrafts(buildPromptDrafts(character, spriteCount, language));
  }, [character, language, spriteCount]);

  const updateDraft = (id: string, patch: Partial<SpritePromptDraft>) => {
    setDrafts((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const refreshPrompts = () => {
    setDrafts(buildPromptDrafts(character, spriteCount, language));
    setGenerationNote(t("aiSprites.promptRefreshed"));
  };

  const refreshOnePrompt = (draft: SpritePromptDraft) => {
    if (!character) {
      return;
    }
    const next = buildPromptDraft(character, draft.index, language);
    updateDraft(draft.id, { label: next.label, prompt: next.prompt, status: "draft" });
    setGenerationNote(t("aiSprites.promptRefreshed"));
  };

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
            disabled={!character}
            icon={<WandSparkles aria-hidden className="button__icon" />}
            onClick={refreshPrompts}
          >
            {t("aiSprites.generatePrompts")}
          </AsyncButton>
        </div>

        {!characters.length ? <EmptyState title={t("character.emptyTitle")} body={t("character.emptyBody")} /> : null}
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
                    onClick={() => refreshOnePrompt(draft)}
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
                  <ImagePlus aria-hidden className="ai-sprite-card__icon" />
                  <span>{t("aiSprites.candidatePlaceholder")}</span>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      <section className="section ai-sprite-page__actions">
        <AsyncButton
          disabled={!hasReadyDraft}
          icon={<Sparkles aria-hidden className="button__icon" />}
          variant="primary"
        >
          {t("aiSprites.generateSelected")}
        </AsyncButton>
        <Button disabled={!hasReadyDraft}>{t("aiSprites.addToCharacter")}</Button>
        <p>{generationNote || t("aiSprites.safeSaveHint")}</p>
      </section>
    </div>
  );
}
