import { useEffect, useMemo, useRef, useState } from "react";
import type { WheelEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  Download,
  ExternalLink,
  Image as ImageIcon,
  Languages,
  Palette,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Tags,
  Trash2,
  Upload,
  Volume2,
} from "lucide-react";

import {
  charactersQueryKey,
  deleteCharacter,
  deleteAllCharacterSprites,
  deleteCharacterMemory,
  deleteCharacterSprite,
  deleteSpriteVoice,
  exportCharacter,
  generateCharacterSetting,
  importCharacters,
  listCharacterMemories,
  listCharacters,
  rememberCharacterMemory,
  saveCharacter,
  saveCharacterEmotionTags,
  saveSpriteScale,
  saveSpriteVoiceText,
  translateCharacterFields,
  uploadCharacterSprites,
  uploadSpriteVoice,
} from "../../entities/character/repository";
import type { Character, Sprite } from "../../entities/config/types";
import { fileUrl, openExternal } from "../../entities/files/repository";
import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";
import { useI18n } from "../../shared/i18n";
import {
  AlertDialog,
  AsyncButton,
  Button,
  Dialog,
  EmptyState,
  FilePicker,
  ImageAssetGallery,
  NumberInput,
  PathDisplay,
  QueryErrorState,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";

function createCharacter(): Character {
  return {
    character_setting: "",
    color: DEFAULT_CHARACTER_COLOR,
    emotion_tags: "",
    name: "",
    pronunciation_map: {},
    speech_speed: 1,
    speech_volume: 1,
    sprite_prefix: "temp",
    sprite_scale: 1,
    sprites: [],
  };
}

function pronunciationMapToText(value: Record<string, string>) {
  return Object.entries(value ?? {})
    .map(([key, item]) => `${key}=${item}`)
    .join("\n");
}

function pronunciationTextToMap(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const index = line.indexOf("=");
      if (index <= 0) {
        return acc;
      }
      const key = line.slice(0, index).trim();
      const item = line.slice(index + 1).trim();
      if (key) {
        acc[key] = item;
      }
      return acc;
    }, {});
}

function importItemsLabel(items: File[] | string[]) {
  return items
    .map((item) => {
      if (typeof File !== "undefined" && item instanceof File) {
        return item.name;
      }
      return String(item).split(/[\\/]/).pop() || String(item);
    })
    .join("; ");
}

function baseName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function extractTagContent(line: string) {
  const fullWidth = line.indexOf("：");
  const ascii = line.indexOf(":");
  const index = fullWidth >= 0 && ascii >= 0 ? Math.min(fullWidth, ascii) : Math.max(fullWidth, ascii);
  return index >= 0 ? line.slice(index + 1).trim() : line.trim();
}

function tagContents(block: string, count: number) {
  const lines = block.split(/\r?\n/).filter(Boolean);
  return Array.from({ length: count }, (_, index) => extractTagContent(lines[index] ?? ""));
}

function numberedTags(prefix: string, tags: string[]) {
  return tags.map((tag, index) => `${prefix} ${index + 1}：${tag}`).join("\n") + (tags.length ? "\n" : "");
}

const SPRITE_SCALE_MIN = 0;
const SPRITE_SCALE_MAX = 3;
const SPRITE_SCALE_STEP = 0.05;

function clampSpriteScale(value: number) {
  return Math.min(SPRITE_SCALE_MAX, Math.max(SPRITE_SCALE_MIN, Number(value.toFixed(2))));
}

export function CharacterEditorPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const data = charactersQuery.data ?? [];
  const isLoading = charactersQuery.isLoading;
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Character>(createCharacter());
  const [isCreating, setIsCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [pendingImportItems, setPendingImportItems] = useState<string[]>([]);
  const [pendingSpritePaths, setPendingSpritePaths] = useState<string[]>([]);
  const [pendingVoicePaths, setPendingVoicePaths] = useState<Record<number, string>>({});
  const [selectedSpriteIndex, setSelectedSpriteIndex] = useState(0);
  const [bulkSpriteTagsOpen, setBulkSpriteTagsOpen] = useState(false);
  const [bulkSpriteTagsDraft, setBulkSpriteTagsDraft] = useState("");
  const [nameError, setNameError] = useState("");
  const [pronunciationText, setPronunciationText] = useState("");
  const [memoryInput, setMemoryInput] = useState("");
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const memoryName = draft.name.trim();
  const currentCharacterName = isCreating ? "" : selectedName;
  const isSavedCharacter = Boolean(
    currentCharacterName && data.some((character) => character.name === currentCharacterName),
  );
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(draft.color || "") ? draft.color : DEFAULT_CHARACTER_COLOR;

  const selected = useMemo(
    () => (isCreating ? undefined : (data.find((character) => character.name === selectedName) ?? data[0])),
    [data, isCreating, selectedName],
  );

  useEffect(() => {
    if (selected) {
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setPronunciationText(pronunciationMapToText(selected.pronunciation_map));
      setPendingSpritePaths([]);
      setPendingVoicePaths({});
      setSelectedSpriteIndex(0);
      setNameError("");
    }
  }, [selected]);

  useEffect(() => {
    setSelectedSpriteIndex((current) => Math.min(current, Math.max(0, draft.sprites.length - 1)));
  }, [draft.sprites.length]);

  const memoryQuery = useQuery({
    enabled: Boolean(memoryName),
    queryFn: () => listCharacterMemories(memoryName),
    queryKey: ["character-memories", memoryName],
  });

  const saveMutation = useMutation({
    mutationFn: ({ character, originalName }: { character: Character; originalName?: string }) =>
      saveCharacter(character, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setIsCreating(false);
      setSelectedName(character.name);
      showToast({ kind: "success", title: t("character.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCharacter,
    onSuccess() {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setPendingDelete(null);
      showToast({ kind: "success", title: t("character.toast.deleted") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: importCharacters,
    onSuccess(imported) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setPendingImportItems([]);
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        setIsCreating(false);
        setSelectedName(lastImported.name);
      }
      showToast({ kind: "success", title: t("character.toast.importComplete", { count: imported.length }) });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.importFallback"),
        title: t("common.importFailed"),
      });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportCharacter,
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("character.toast.exportComplete") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.exportFallback"),
        title: t("common.exportFailed"),
      });
    },
  });

  const aiSettingMutation = useMutation({
    mutationFn: () => generateCharacterSetting({ name: draft.name.trim(), setting: draft.character_setting }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("character.action.aiWrite"),
      });
    },
    onSuccess(result) {
      update("character_setting", result.characterSetting);
      showToast({ kind: "success", message: result.message, title: t("character.action.aiWrite") });
    },
  });

  const translateMutation = useMutation({
    mutationFn: () =>
      translateCharacterFields({
        characterSetting: draft.character_setting,
        emotionTags: draft.emotion_tags,
        name: draft.name,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.translateFallback"),
        title: t("character.action.aiTranslate"),
      });
    },
    onSuccess(result) {
      if (result.error) {
        showToast({ kind: "error", message: result.error, title: t("character.action.aiTranslate") });
        return;
      }
      setDraft((current) => ({
        ...current,
        character_setting: result.characterSetting,
        emotion_tags: result.emotionTags,
        name: result.name,
      }));
      if (result.name.trim()) {
        setNameError("");
      }
      showToast({ kind: "success", title: t("character.action.aiTranslate") });
    },
  });

  const memoryAddMutation = useMutation({
    mutationFn: () => rememberCharacterMemory(memoryName, memoryInput),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.add"),
      });
    },
    onSuccess(result) {
      setMemoryInput("");
      queryClient.setQueryData(["character-memories", memoryName], result);
      showToast({ kind: "success", title: t("character.memory.add") });
    },
  });

  const memoryDeleteMutation = useMutation({
    mutationFn: (memoryId: string) => deleteCharacterMemory(memoryName, memoryId),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.delete"),
      });
    },
    onSuccess(result) {
      queryClient.setQueryData(["character-memories", memoryName], result);
    },
  });

  const voiceUploadMutation = useMutation({
    mutationFn: ({ index, voicePath, voiceText }: { index: number; voicePath: string; voiceText: string }) =>
      uploadSpriteVoice({
        name: currentCharacterName,
        spriteIndex: index,
        voicePath,
        voiceText,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.uploadVoice"),
      });
    },
    onSuccess(character, variables) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, sprites: character.sprites }));
      setPendingVoicePaths((current) => {
        const next = { ...current };
        delete next[variables.index];
        return next;
      });
      showToast({ kind: "success", title: t("character.sprite.uploadVoice") });
    },
  });

  const voiceTextMutation = useMutation({
    mutationFn: ({ index, text }: { index: number; text: string }) =>
      saveSpriteVoiceText(currentCharacterName, index, text),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.saveVoiceText"),
      });
    },
    onSuccess(character, variables) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => {
        const sprites = [...current.sprites];
        const returned = character.sprites[variables.index];
        if (returned && sprites[variables.index]) {
          sprites[variables.index] = {
            ...sprites[variables.index],
            voice_path: returned.voice_path || sprites[variables.index].voice_path,
            voice_text: returned.voice_text ?? "",
          };
        }
        return { ...current, sprites };
      });
      showToast({ kind: "success", title: t("character.sprite.saveVoiceText") });
    },
  });

  const voiceDeleteMutation = useMutation({
    mutationFn: (index: number) => deleteSpriteVoice(currentCharacterName, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.deleteVoice"),
      });
    },
    onSuccess(character, index) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, sprites: character.sprites }));
      setPendingVoicePaths((current) => {
        const next = { ...current };
        delete next[index];
        return next;
      });
      showToast({ kind: "success", title: t("character.sprite.deleteVoice") });
    },
  });

  const spriteUploadMutation = useMutation({
    mutationFn: () => {
      return uploadCharacterSprites({
        emotionTags: draft.emotion_tags,
        name: currentCharacterName,
        paths: pendingSpritePaths,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.uploadImages"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, emotion_tags: character.emotion_tags, sprites: character.sprites }));
      setPendingSpritePaths([]);
      showToast({ kind: "success", title: t("character.sprite.uploadImages") });
    },
  });

  const emotionTagsMutation = useMutation({
    mutationFn: () => saveCharacterEmotionTags(currentCharacterName, draft.emotion_tags),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.saveTags"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, emotion_tags: character.emotion_tags }));
      showToast({ kind: "success", title: t("character.sprite.saveTags") });
    },
  });

  const spriteDeleteMutation = useMutation({
    mutationFn: (index: number) => deleteCharacterSprite(currentCharacterName, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("common.remove"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, emotion_tags: character.emotion_tags, sprites: character.sprites }));
      showToast({ kind: "success", title: t("common.remove") });
    },
  });

  const spriteDeleteAllMutation = useMutation({
    mutationFn: () => deleteAllCharacterSprites(currentCharacterName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.clear"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, emotion_tags: character.emotion_tags, sprites: character.sprites }));
      showToast({ kind: "success", title: t("character.sprite.clear") });
    },
  });

  const spriteScaleMutation = useMutation({
    mutationFn: () => saveSpriteScale(currentCharacterName, Number(draft.sprite_scale) || 0),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.saveScale"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, sprite_scale: character.sprite_scale }));
      showToast({ kind: "success", title: t("character.sprite.saveScale") });
    },
  });

  const update = <K extends keyof Character>(name: K, value: Character[K]) => {
    setDraft((current) => ({ ...current, [name]: value }));
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
  };

  const updateSprite = (index: number, patch: Partial<Sprite>) => {
    setDraft((current) => {
      const sprites = [...current.sprites];
      sprites[index] = { ...sprites[index], ...patch };
      return { ...current, sprites };
    });
  };

  const updateSpriteTag = (index: number, value: string) => {
    setDraft((current) => {
      const tags = tagContents(current.emotion_tags, current.sprites.length);
      tags[index] = value;
      return { ...current, emotion_tags: numberedTags("立绘", tags) };
    });
  };

  const openBulkSpriteTagsDialog = () => {
    setBulkSpriteTagsDraft(draft.emotion_tags);
    setBulkSpriteTagsOpen(true);
  };

  const handleSpriteScaleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const direction = event.deltaY < 0 ? 1 : -1;
    const current = Number(draft.sprite_scale) || 0;
    update("sprite_scale", clampSpriteScale(current + direction * SPRITE_SCALE_STEP));
  };

  const saveDraft = () => {
    if (!draft.name.trim()) {
      setNameError(t("character.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    const spritePrefix = draft.sprite_prefix.trim();
    const pathFields = [draft.gpt_model_path, draft.sovits_model_path, draft.refer_audio_path]
      .filter(Boolean)
      .map(String);
    const validationMessages = [
      !spritePrefix ? t("character.validation.spritePrefixRequired") : "",
      spritePrefix && !/^[\x00-\x7F]+$/.test(spritePrefix) ? t("character.validation.spritePrefixAscii") : "",
      pathFields.some((path) => path.trim().startsWith('"') || path.trim().endsWith('"'))
        ? t("character.validation.noQuotedPaths")
        : "",
      draft.gpt_model_path?.trim() && !draft.gpt_model_path.trim().toLowerCase().endsWith(".ckpt")
        ? t("character.validation.gptModelExt")
        : "",
      draft.sovits_model_path?.trim() && !draft.sovits_model_path.trim().toLowerCase().endsWith(".pth")
        ? t("character.validation.sovitsModelExt")
        : "",
    ].filter(Boolean);
    if (validationMessages.length) {
      showToast({
        kind: "error",
        message: validationMessages.join("\n"),
        title: t("common.validationFailed"),
      });
      return;
    }
    saveMutation.mutate({
      character: {
        ...draft,
        character_setting: draft.character_setting.trim(),
        color: draft.color.trim() || DEFAULT_CHARACTER_COLOR,
        gpt_model_path: draft.gpt_model_path?.trim() || "",
        name: draft.name.trim(),
        prompt_lang: draft.prompt_lang?.trim() || "",
        prompt_text: draft.prompt_text?.trim() || "",
        pronunciation_map: pronunciationTextToMap(pronunciationText),
        refer_audio_path: draft.refer_audio_path?.trim() || "",
        sovits_model_path: draft.sovits_model_path?.trim() || "",
        sprite_prefix: spritePrefix,
      },
      originalName: isCreating ? undefined : selectedName,
    });
  };

  const spriteTags = useMemo(
    () => tagContents(draft.emotion_tags, draft.sprites.length),
    [draft.emotion_tags, draft.sprites.length],
  );
  const selectedSprite = draft.sprites[selectedSpriteIndex];
  const selectedSpriteTag = spriteTags[selectedSpriteIndex] ?? "";
  const spriteGalleryItems = useMemo(
    () =>
      draft.sprites.map((sprite, index) => ({
        badge: sprite.voice_path ? t("character.sprite.hasVoice") : t("character.sprite.noVoice"),
        badgeTone: sprite.voice_path ? ("default" as const) : ("muted" as const),
        id: `${sprite.path}-${index}`,
        imageSrc: sprite.path ? fileUrl(sprite.path) : "",
        meta: spriteTags[index] || sprite.voice_text || "",
        title: baseName(sprite.path) || `${index + 1}`,
      })),
    [draft.sprites, spriteTags, t],
  );

  return (
    <div className="page character-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("character.title")}</h1>
          <p className="page__description">{t("character.description")}</p>
        </div>
        <div className="page__actions">
          <Button
            icon={<Plus aria-hidden className="button__icon" />}
            onClick={() => {
              setIsCreating(true);
              setSelectedName("");
              setDraft(createCharacter());
              setPronunciationText("");
              setPendingSpritePaths([]);
              setPendingVoicePaths({});
              setSelectedSpriteIndex(0);
              setNameError("");
            }}
          >
            {t("common.new")}
          </Button>
          <div className="page__file-picker">
            <FilePicker
              acceptedExtensions={[".char", ".cha"]}
              multiple
              onPathsChange={setPendingImportItems}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("common.import")}
              placeholder={t("character.import.noFile")}
              readOnly
              value={pendingImportItems.length ? importItemsLabel(pendingImportItems) : ""}
            />
          </div>
          <AsyncButton
            disabled={!pendingImportItems.length}
            icon={<Upload aria-hidden className="button__icon" />}
            loading={importMutation.isPending}
            onClick={() => {
              importMutation.mutate(pendingImportItems);
            }}
          >
            {t("common.import")}
          </AsyncButton>
          <AsyncButton
            icon={<Download aria-hidden className="button__icon" />}
            loading={exportMutation.isPending}
            onClick={() => {
              if (!currentCharacterName) {
                showToast({
                  kind: "error",
                  message: t("character.validation.nameRequired"),
                  title: t("common.export"),
                });
                return;
              }
              exportMutation.mutate(currentCharacterName);
            }}
          >
            {t("common.export")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={saveMutation.isPending}
            onClick={saveDraft}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal("https://rachelforster.github.io/Shinsekai/resources.html?type=character")}
            variant="ghost"
          >
            {t("character.action.community")}
          </Button>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal("https://wj.qq.com/s2/26613318/4fd2/")}
            variant="ghost"
          >
            {t("character.action.uploadContribution")}
          </Button>
        </div>
      </header>

      <section className="section character-page__file-box">
        <div className="form-grid">
          <label className="field-row">
            <span className="field-row__label">{t("character.row.current")}</span>
            <span className="field-row__control">
              <Select
                disabled={isLoading || !data.length}
                onChange={(event) => {
                  setIsCreating(false);
                  setSelectedName(event.target.value);
                }}
                value={isCreating ? "" : selectedName || data[0]?.name || ""}
              >
                {isCreating ? <option value="">{t("common.new")}</option> : null}
                {data.map((character) => (
                  <option key={character.name} value={character.name}>
                    {character.name}
                  </option>
                ))}
              </Select>
            </span>
          </label>
        </div>
      </section>

      <div className="settings-grid settings-grid--split">
        <aside className="entity-list">
          <div className="entity-list__header">
            <strong>{t("character.listTitle")}</strong>
            <span className="entity-list__meta">{data.length}</span>
          </div>
          {isLoading ? <EmptyState title={t("character.loading")} /> : null}
          {charactersQuery.isError ? (
            <QueryErrorState
              error={charactersQuery.error}
              onRetry={() => void charactersQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!isLoading && !charactersQuery.isError && !data.length ? (
            <EmptyState title={t("character.emptyTitle")} body={t("character.emptyBody")} />
          ) : null}
          {data.map((character) => (
            <button
              aria-selected={!isCreating && character.name === draft.name}
              className="entity-list__item"
              key={character.name}
              onClick={() => {
                setIsCreating(false);
                setSelectedName(character.name);
              }}
              type="button"
            >
              <span className="entity-list__primary">{character.name}</span>
              <span className="swatch" style={{ background: character.color }} />
            </button>
          ))}
        </aside>

        <section className="settings-grid">
          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("character.section.basic")}</h2>
              <Button
                icon={<Trash2 aria-hidden className="button__icon" />}
                onClick={() => {
                  if (!currentCharacterName) {
                    showToast({
                      kind: "error",
                      message: t("character.validation.nameRequired"),
                      title: t("common.delete"),
                    });
                    return;
                  }
                  setPendingDelete(currentCharacterName);
                }}
                variant="danger"
              >
                {t("common.delete")}
              </Button>
            </div>
            <div className="form-grid form-grid--two">
              <label className="field-row">
                <span className="field-row__label">{t("character.field.name")}</span>
                <span className="field-row__control">
                  <TextInput
                    className={nameError ? "input--error" : ""}
                    onChange={(event) => update("name", event.target.value)}
                    value={draft.name}
                  />
                  {nameError ? <span className="field-error">{nameError}</span> : null}
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.color")}</span>
                <span className="field-row__control">
                  <div className="input-group character-color-control">
                    <TextInput onChange={(event) => update("color", event.target.value)} value={draft.color} />
                    <span aria-hidden className="swatch" style={{ background: draft.color }} />
                    <Button
                      icon={<Palette aria-hidden className="button__icon" />}
                      onClick={() => colorInputRef.current?.click()}
                      variant="ghost"
                    >
                      {t("character.action.pickColor")}
                    </Button>
                    <input
                      className="visually-hidden"
                      onChange={(event) => update("color", event.target.value)}
                      ref={colorInputRef}
                      type="color"
                      value={colorPickerValue}
                    />
                  </div>
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.spritePrefix")}</span>
                <span className="field-row__control">
                  <TextInput
                    onChange={(event) => update("sprite_prefix", event.target.value)}
                    value={draft.sprite_prefix}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.pronunciationMap")}</span>
                <span className="field-row__control">
                  <TextArea
                    onChange={(event) => setPronunciationText(event.target.value)}
                    placeholder="名前=なまえ"
                    rows={4}
                    value={pronunciationText}
                  />
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("character.section.personality")}</h2>
              <div className="page__actions">
                <AsyncButton
                  icon={<Sparkles aria-hidden className="button__icon" />}
                  loading={aiSettingMutation.isPending}
                  onClick={() => {
                    if (!draft.name.trim()) {
                      setNameError(t("character.validation.nameRequired"));
                      showToast({
                        kind: "error",
                        message: t("common.fixInvalidFields"),
                        title: t("common.validationFailed"),
                      });
                      return;
                    }
                    aiSettingMutation.mutate();
                  }}
                >
                  {t("character.action.aiWrite")}
                </AsyncButton>
                <AsyncButton
                  icon={<Languages aria-hidden className="button__icon" />}
                  loading={translateMutation.isPending}
                  onClick={() => {
                    if (!draft.name.trim() && !draft.character_setting.trim() && !draft.emotion_tags.trim()) {
                      showToast({
                        kind: "error",
                        message: t("common.fixInvalidFields"),
                        title: t("common.validationFailed"),
                      });
                      return;
                    }
                    translateMutation.mutate();
                  }}
                  variant="ghost"
                >
                  {t("character.action.aiTranslate")}
                </AsyncButton>
              </div>
            </div>
            <div className="form-grid">
              <label className="field-row">
                <span className="field-row__label">{t("character.field.characterSetting")}</span>
                <span className="field-row__control">
                  <TextArea
                    onChange={(event) => update("character_setting", event.target.value)}
                    value={draft.character_setting}
                  />
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("character.section.voice")}</h2>
            </div>
            <div className="form-grid form-grid--two">
              <label className="field-row">
                <span className="field-row__label">{t("character.field.gptModel")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".ckpt"]}
                    onChange={(event) => update("gpt_model_path", event.target.value)}
                    onPathChange={(path) => update("gpt_model_path", path)}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("character.field.gptModel")}
                    readOnly={false}
                    value={draft.gpt_model_path ?? ""}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.sovitsModel")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".pth"]}
                    onChange={(event) => update("sovits_model_path", event.target.value)}
                    onPathChange={(path) => update("sovits_model_path", path)}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("character.field.sovitsModel")}
                    readOnly={false}
                    value={draft.sovits_model_path ?? ""}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.referAudio")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
                    onChange={(event) => update("refer_audio_path", event.target.value)}
                    onPathChange={(path) => update("refer_audio_path", path)}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("character.field.referAudio")}
                    readOnly={false}
                    value={draft.refer_audio_path ?? ""}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.promptLang")}</span>
                <span className="field-row__control">
                  <TextInput
                    onChange={(event) => update("prompt_lang", event.target.value)}
                    value={draft.prompt_lang ?? ""}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.promptText")}</span>
                <span className="field-row__control">
                  <TextInput
                    onChange={(event) => update("prompt_text", event.target.value)}
                    value={draft.prompt_text ?? ""}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.speechSpeed")}</span>
                <span className="field-row__control">
                  <NumberInput
                    max={5}
                    min={0.1}
                    onChange={(event) => update("speech_speed", Number(event.target.value))}
                    step={0.05}
                    value={draft.speech_speed}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("character.field.speechVolume")}</span>
                <span className="field-row__control">
                  <NumberInput
                    max={2}
                    min={0}
                    onChange={(event) => update("speech_volume", Number(event.target.value))}
                    step={0.1}
                    value={draft.speech_volume}
                  />
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("character.section.sprites")}</h2>
              <div className="page__actions">
                <AsyncButton
                  icon={<Upload aria-hidden className="button__icon" />}
                  loading={spriteUploadMutation.isPending}
                  onClick={() => {
                    if (!isSavedCharacter) {
                      showToast({
                        kind: "error",
                        message: t("character.validation.nameRequired"),
                        title: t("character.sprite.uploadImages"),
                      });
                      return;
                    }
                    if (!pendingSpritePaths.length) {
                      showToast({ kind: "error", title: t("character.sprite.selectImages") });
                      return;
                    }
                    spriteUploadMutation.mutate();
                  }}
                  variant="ghost"
                >
                  {t("character.sprite.uploadImages")}
                </AsyncButton>
                <Button
                  disabled={!draft.sprites.length}
                  icon={<Tags aria-hidden className="button__icon" />}
                  onClick={openBulkSpriteTagsDialog}
                  variant="ghost"
                >
                  {t("character.sprite.batchTags")}
                </Button>
                <Button
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  onClick={() => {
                    if (!isSavedCharacter || !draft.sprites.length) {
                      showToast({ kind: "error", title: t("character.sprite.clear") });
                      return;
                    }
                    spriteDeleteAllMutation.mutate();
                  }}
                  variant="ghost"
                >
                  {t("character.sprite.clear")}
                </Button>
              </div>
            </div>
            <div className="asset-editor">
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.selectImages")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                    multiple
                    onPathsChange={(paths) => {
                      if (paths.length) {
                        setPendingSpritePaths(paths);
                      }
                    }}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("character.sprite.selectImages")}
                    value={
                      pendingSpritePaths.length
                        ? t("character.sprite.selectedFiles", { count: pendingSpritePaths.length })
                        : ""
                    }
                  />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.field.spriteScale")}</span>
                <span className="field-row__control">
                  <div className="input-group character-scale-control" onWheel={handleSpriteScaleWheel}>
                    <NumberInput
                      max={SPRITE_SCALE_MAX}
                      min={SPRITE_SCALE_MIN}
                      onChange={(event) => update("sprite_scale", Number(event.target.value))}
                      step={SPRITE_SCALE_STEP}
                      value={draft.sprite_scale}
                    />
                    <AsyncButton
                      loading={spriteScaleMutation.isPending}
                      onClick={() => {
                        if (!isSavedCharacter) {
                          showToast({
                            kind: "error",
                            message: t("character.validation.nameRequired"),
                            title: t("character.sprite.saveScale"),
                          });
                          return;
                        }
                        spriteScaleMutation.mutate();
                      }}
                    >
                      {t("character.sprite.saveScale")}
                    </AsyncButton>
                  </div>
                </span>
              </label>
              {!draft.sprites.length ? <EmptyState title={t("character.sprite.empty")} /> : null}
              {selectedSprite ? (
                <div className="asset-gallery-layout asset-gallery-layout--character">
                  <ImageAssetGallery
                    items={spriteGalleryItems}
                    onSelect={setSelectedSpriteIndex}
                    selectedIndex={selectedSpriteIndex}
                  />
                  <aside className="asset-inspector">
                    <div className="asset-inspector__preview asset-inspector__preview--character">
                      {selectedSprite.path ? (
                        <img alt="" decoding="async" src={fileUrl(selectedSprite.path)} />
                      ) : (
                        <ImageIcon aria-hidden className="asset-inspector__fallback" />
                      )}
                    </div>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("character.sprite.tag")}</span>
                      <span className="field-row__control">
                        <div className="input-group sprite-tag-row">
                          <TextInput
                            onChange={(event) => updateSpriteTag(selectedSpriteIndex, event.target.value)}
                            value={selectedSpriteTag}
                          />
                          <AsyncButton
                            loading={emotionTagsMutation.isPending}
                            onClick={() => {
                              if (!isSavedCharacter || !draft.emotion_tags) {
                                showToast({
                                  kind: "error",
                                  message: t("common.fixInvalidFields"),
                                  title: t("character.sprite.saveTags"),
                                });
                                return;
                              }
                              emotionTagsMutation.mutate();
                            }}
                            variant="ghost"
                          >
                            {t("character.sprite.saveTags")}
                          </AsyncButton>
                        </div>
                      </span>
                    </label>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("character.sprite.path")}</span>
                      <span className="field-row__control">
                        <PathDisplay className="path-display--input" path={selectedSprite.path} />
                      </span>
                    </label>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("character.sprite.voicePath")}</span>
                      <span className="field-row__control">
                        <PathDisplay className="path-display--input" path={selectedSprite.voice_path ?? ""} />
                        {selectedSprite.voice_path ? (
                          <audio
                            className="audio-inline"
                            controls
                            preload="none"
                            src={fileUrl(selectedSprite.voice_path)}
                          />
                        ) : null}
                      </span>
                    </label>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("character.sprite.voiceUploadPath")}</span>
                      <span className="field-row__control">
                        <FilePicker
                          acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
                          onPathChange={(path) =>
                            setPendingVoicePaths((current) => ({ ...current, [selectedSpriteIndex]: path }))
                          }
                          pickLabel={t("common.chooseFile")}
                          pickerTitle={t("character.sprite.voiceUploadPath")}
                          value={pendingVoicePaths[selectedSpriteIndex] ?? ""}
                        />
                      </span>
                    </label>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("character.sprite.voiceText")}</span>
                      <span className="field-row__control">
                        <TextInput
                          onBlur={(event) => {
                            const text = event.currentTarget.value;
                            const savedText = selected?.sprites[selectedSpriteIndex]?.voice_text ?? "";
                            if (currentCharacterName && text !== savedText && !voiceTextMutation.isPending) {
                              voiceTextMutation.mutate({ index: selectedSpriteIndex, text });
                            }
                          }}
                          onChange={(event) => updateSprite(selectedSpriteIndex, { voice_text: event.target.value })}
                          value={selectedSprite.voice_text ?? ""}
                        />
                      </span>
                    </label>
                    <div className="asset-inspector__actions">
                      <AsyncButton
                        loading={voiceUploadMutation.isPending}
                        onClick={() => {
                          const voicePath = pendingVoicePaths[selectedSpriteIndex]?.trim() ?? "";
                          if (!isSavedCharacter) {
                            showToast({
                              kind: "error",
                              message: t("character.validation.nameRequired"),
                              title: t("character.sprite.uploadVoice"),
                            });
                            return;
                          }
                          if (!voicePath) {
                            showToast({ kind: "error", title: t("character.sprite.voiceUploadPath") });
                            return;
                          }
                          voiceUploadMutation.mutate({
                            index: selectedSpriteIndex,
                            voicePath,
                            voiceText: selectedSprite.voice_text ?? "",
                          });
                        }}
                        variant="ghost"
                      >
                        {t("character.sprite.uploadVoice")}
                      </AsyncButton>
                      <AsyncButton
                        loading={voiceDeleteMutation.isPending}
                        onClick={() => {
                          if (!currentCharacterName || !selectedSprite.voice_path) {
                            showToast({ kind: "error", title: t("character.sprite.deleteVoice") });
                            return;
                          }
                          voiceDeleteMutation.mutate(selectedSpriteIndex);
                        }}
                        variant="ghost"
                      >
                        {t("character.sprite.deleteVoice")}
                      </AsyncButton>
                      <AsyncButton
                        icon={<Trash2 aria-hidden className="button__icon" />}
                        loading={spriteDeleteMutation.isPending}
                        onClick={() => spriteDeleteMutation.mutate(selectedSpriteIndex)}
                        variant="ghost"
                      >
                        {t("common.remove")}
                      </AsyncButton>
                    </div>
                  </aside>
                </div>
              ) : null}
            </div>
            <div className="inline-status">
              <Volume2 aria-hidden className="button__icon" />
              {t("character.sprite.voiceHint")}
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("character.memory.section")}</h2>
              <div className="page__actions">
                <span className="entity-list__meta">
                  {memoryQuery.data ? t("character.memory.count", { count: memoryQuery.data.count }) : ""}
                </span>
                <Button
                  disabled={!memoryName || memoryQuery.isFetching}
                  icon={<RefreshCw aria-hidden className="button__icon" />}
                  onClick={() => memoryQuery.refetch()}
                  variant="ghost"
                >
                  {t("character.memory.refresh")}
                </Button>
              </div>
            </div>
            {!memoryName ? <EmptyState title={t("character.memory.nameRequired")} /> : null}
            {memoryName && memoryQuery.isLoading ? <EmptyState title={t("character.memory.loading")} /> : null}
            {memoryName && memoryQuery.isError ? (
              <QueryErrorState
                body={t("character.memory.error")}
                error={memoryQuery.error}
                onRetry={() => void memoryQuery.refetch()}
                retryLabel={t("common.retry")}
                title={t("common.operationFailed")}
              />
            ) : null}
            {memoryName && !memoryQuery.isLoading && !memoryQuery.isError && !memoryQuery.data?.memories.length ? (
              <EmptyState title={t("character.memory.empty")} />
            ) : null}
            {memoryQuery.data?.memories.length ? (
              <div className="memory-table">
                {memoryQuery.data.memories.map((memory) => (
                  <div className="memory-row" key={memory.id || memory.memory}>
                    <Brain aria-hidden className="asset-row__icon" />
                    <div className="memory-row__content">
                      <strong>{memory.memory}</strong>
                      <span>{memory.id}</span>
                    </div>
                    <AsyncButton
                      disabled={!memory.id}
                      loading={memoryDeleteMutation.isPending}
                      onClick={() => memoryDeleteMutation.mutate(memory.id)}
                      variant="ghost"
                    >
                      {t("character.memory.delete")}
                    </AsyncButton>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="memory-add-row">
              <TextInput
                disabled={!memoryName}
                onChange={(event) => setMemoryInput(event.target.value)}
                placeholder={t("character.memory.placeholder")}
                value={memoryInput}
              />
              <AsyncButton
                disabled={!memoryName || !memoryInput.trim()}
                loading={memoryAddMutation.isPending}
                onClick={() => memoryAddMutation.mutate()}
              >
                {t("character.memory.add")}
              </AsyncButton>
            </div>
          </section>
        </section>
      </div>

      <Dialog
        bodyClassName="sprite-tags-dialog__body"
        className="sprite-tags-dialog"
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={() => setBulkSpriteTagsOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => {
                update("emotion_tags", bulkSpriteTagsDraft);
                setBulkSpriteTagsOpen(false);
              }}
              variant="primary"
            >
              {t("common.confirm")}
            </Button>
          </>
        }
        onClose={() => setBulkSpriteTagsOpen(false)}
        open={bulkSpriteTagsOpen}
        title={t("character.sprite.batchTagsTitle")}
      >
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("character.field.emotionTags")}</span>
          <span className="field-row__control">
            <TextArea
              onChange={(event) => setBulkSpriteTagsDraft(event.target.value)}
              rows={12}
              value={bulkSpriteTagsDraft}
            />
          </span>
        </label>
        <p className="sprite-tags-dialog__hint">{t("character.sprite.batchTagsHelp")}</p>
      </Dialog>

      <AlertDialog
        body={t("character.delete.confirmBody", { name: pendingDelete ?? "" })}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.delete")}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete)}
        open={Boolean(pendingDelete)}
        title={t("character.delete.confirmTitle")}
      />
    </div>
  );
}
