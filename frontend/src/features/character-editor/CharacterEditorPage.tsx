import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { WheelEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import {
  charactersQueryKey,
  deleteCharacter,
  deleteAllCharacterSprites,
  deleteCharacterMemory,
  deleteCharacterSprite,
  deleteSpriteVoice,
  exportCharacter,
  generateCharacterSetting,
  getMem0Status,
  importCharacters,
  listCharacterMemories,
  listCharacters,
  rememberCharacterMemory,
  saveCharacter,
  saveCharacterEmotionTags,
  saveSpriteScale,
  saveSpriteVoiceText,
  saveSpriteVoiceType,
  translateCharacterFields,
  uploadCharacterSprites,
  uploadSpriteVoice,
} from "../../entities/character/repository";
import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import type { Character, Sprite } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { baseName, numberedTags, tagContents } from "../../shared/assets/assetText";
import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import { AlertDialog, Button, Dialog, PageSectionNav, TaskProgress, useToast } from "../../shared/ui";
import { CharacterBasicSection } from "./CharacterBasicSection";
import { CharacterMemorySection } from "./CharacterMemorySection";
import { CharacterPageHeader } from "./CharacterPageHeader";
import { CharacterPersonalitySection } from "./CharacterPersonalitySection";
import { CharacterSpritesSection } from "./CharacterSpritesSection";
import { CharacterVoiceSection } from "./CharacterVoiceSection";
import { SpriteTagsDialog } from "./SpriteTagsDialog";
import {
  SPRITE_SCALE_STEP,
  clampSpriteScale,
  createCharacter,
  pronunciationMapToText,
  pronunciationTextToMap,
  type CharacterResourceDeleteTarget,
} from "./characterEditorUtils";
import "./CharacterEditorPage.css";

export function CharacterEditorPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const data = charactersQuery.data ?? [];
  const isLoading = charactersQuery.isLoading;
  const voiceReferenceReadOnly = configQuery.data?.api_config?.tts_provider === "kaggle-gpt-sovits";
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Character>(createCharacter());
  const [isCreating, setIsCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [pendingResourceDelete, setPendingResourceDelete] = useState<CharacterResourceDeleteTarget | null>(null);
  const [pendingSpritePaths, setPendingSpritePaths] = useState<string[]>([]);
  const [pendingVoicePaths, setPendingVoicePaths] = useState<Record<number, string>>({});
  const [selectedSpriteIndex, setSelectedSpriteIndex] = useState(0);
  const [bulkSpriteTagsOpen, setBulkSpriteTagsOpen] = useState(false);
  const [bulkSpriteTagsDraft, setBulkSpriteTagsDraft] = useState("");
  const [nameError, setNameError] = useState("");
  const [pronunciationText, setPronunciationText] = useState("");
  const [memoryInput, setMemoryInput] = useState("");
  const [memoryDepOpen, setMemoryDepOpen] = useState(false);
  const [memoryDepInstalling, setMemoryDepInstalling] = useState(false);
  const [memoryDepTask, setMemoryDepTask] = useState<TaskSnapshot | null>(null);
  const [mem0LoadingOpen, setMem0LoadingOpen] = useState(false);
  const [mem0LoadingMessage, setMem0LoadingMessage] = useState("");
  const [mem0Checking, setMem0Checking] = useState(false);
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const memoryName = draft.name.trim();
  const currentCharacterName = isCreating ? "" : selectedName;
  const isSavedCharacter = Boolean(
    currentCharacterName && data.some((character) => character.name === currentCharacterName),
  );
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(draft.color || "") ? draft.color : DEFAULT_CHARACTER_COLOR;
  const setColorInputElement = useCallback((element: HTMLInputElement | null) => {
    colorInputRef.current = element;
  }, []);
  const openColorPicker = useCallback(() => {
    colorInputRef.current?.click();
  }, []);

  const selected = useMemo(() => {
    if (isCreating) {
      return undefined;
    }
    if (selectedName) {
      return data.find((character) => character.name === selectedName);
    }
    return data[0];
  }, [data, isCreating, selectedName]);

  const prevSelectedNameRef = useRef<string>("");
  useEffect(() => {
    if (selected && selected.name !== prevSelectedNameRef.current) {
      prevSelectedNameRef.current = selected.name;
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setPronunciationText(pronunciationMapToText(selected.pronunciation_map));
      setPendingSpritePaths([]);
      setPendingVoicePaths({});
      setSelectedSpriteIndex(0);
      setNameError("");
    } else if (selected) {
      // same character, just sync draft silently (e.g. after invalidateQueries)
      setDraft(structuredClone(selected));
    }
  }, [selected]);

  useEffect(() => {
    setSelectedSpriteIndex((current) => Math.min(current, Math.max(0, draft.sprites.length - 1)));
  }, [draft.sprites.length]);

  const memoryQuery = useQuery({
    enabled: false,
    queryFn: () => listCharacterMemories(memoryName),
    queryKey: ["character-memories", memoryName],
  });

  const memoryDepError: { kind: string; moduleName: string; packageName: string } | null = useMemo(() => {
    const data = memoryQuery.data as Record<string, unknown> | undefined;
    if (data && typeof data.kind === "string" && data.kind === "missing_dependency") {
      return {
        kind: data.kind,
        moduleName: String(data.moduleName || ""),
        packageName: String(data.packageName || ""),
      };
    }
    return null;
  }, [memoryQuery.data]);

  const installMemoryDep = async () => {
    if (!memoryDepError) {
      return;
    }
    setMemoryDepInstalling(true);
    setMemoryDepOpen(true);
    setMemoryDepTask(null);
    try {
      await installMissingRuntimeDependency(
        { moduleName: memoryDepError.moduleName },
        { onTaskUpdate: (task) => setMemoryDepTask(task) },
      );
      showToast({ kind: "success", title: t("character.memory.depInstalled") });
      setMemoryDepOpen(false);
      setMemoryDepTask(null);
      void memoryQuery.refetch();
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.depInstallFailed"),
        title: t("character.memory.depInstallFailed"),
      });
    } finally {
      setMemoryDepInstalling(false);
    }
  };

  // 确保 mem0 就绪：缺依赖→弹安装窗 / 首次下载模型→弹等待窗 / 模型已缓存→静默加载。
  // 返回 true 表示可以继续操作，false 表示需要等待或已处理。
  const ensureMem0Ready = async (): Promise<boolean> => {
    setMem0Checking(true);
    try {
      const status = await getMem0Status();
      if (status.status === "missing_dependency") {
        void memoryQuery.refetch();
        return false;
      }
      if (status.status === "loading" || status.status === "not_started") {
        // 模型已缓存 → 弹窗 "加载"；未缓存 → 弹窗 "下载"
        setMem0LoadingMessage(
          status.modelCached ? t("character.memory.loadingModel") : t("character.memory.downloadingModel"),
        );
        setMem0LoadingOpen(true);
        const pollMs = status.modelCached ? 2000 : 3000;
        let pollStatus = status;
        while (pollStatus.status === "loading" || pollStatus.status === "not_started") {
          await new Promise((r) => setTimeout(r, pollMs));
          try {
            pollStatus = await getMem0Status();
          } catch {
            break;
          }
        }
        setMem0LoadingOpen(false);
        if (pollStatus.status === "missing_dependency") {
          void memoryQuery.refetch();
          return false;
        }
        if (pollStatus.status === "error") {
          showToast({
            kind: "error",
            message: pollStatus.message || t("character.memory.error"),
            title: t("common.operationFailed"),
          });
          return false;
        }
      }
      return true;
    } catch {
      return true;
    } finally {
      setMem0Checking(false);
    }
  };

  const refreshMemories = async () => {
    if (!memoryName) return;
    if (!(await ensureMem0Ready())) return;
    void memoryQuery.refetch();
  };

  const addMemory = async () => {
    if (!(await ensureMem0Ready())) return;
    memoryAddMutation.mutate();
  };

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
    onSuccess(character, variables) {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) => {
        const targetNames = new Set([variables.originalName, character.name].filter(Boolean));
        const next = current.filter((item) => !targetNames.has(item.name));
        return [...next, character];
      });
      setIsCreating(false);
      setSelectedName(character.name);
      setDraft(structuredClone(character));
      setPronunciationText(pronunciationMapToText(character.pronunciation_map));
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
    mutationFn: ({ memoryId, name }: { memoryId: string; name: string }) => deleteCharacterMemory(name, memoryId),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.delete"),
      });
    },
    onSuccess(result, variables) {
      queryClient.setQueryData(["character-memories", variables.name], result);
    },
  });

  const voiceUploadMutation = useMutation({
    mutationFn: ({ index, voicePath, voiceText }: { index: number; voicePath: string; voiceText: string }) =>
      uploadSpriteVoice({
        name: currentCharacterName,
        spriteIndex: index,
        voicePath,
        voiceText,
        voiceType: spriteVoiceType(draft.sprites[index], draft),
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
      setDraft((current) => ({
        ...current,
        sprites: mergeSprites(character.sprites, current),
      }));
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

  const voiceTypeMutation = useMutation({
    mutationFn: ({ index, voiceType: vt }: { index: number; voiceType: string }) =>
      saveSpriteVoiceType(currentCharacterName, index, vt),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.voiceType"),
      });
    },
  });

  const voiceDeleteMutation = useMutation({
    mutationFn: ({ index, name }: { index: number; name: string }) => deleteSpriteVoice(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.deleteVoice"),
      });
    },
    onSuccess(character, variables) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({
        ...current,
        sprites: mergeSprites(character.sprites, current),
      }));
      setPendingVoicePaths((current) => {
        const next = { ...current };
        delete next[variables.index];
        return next;
      });
      showToast({ kind: "success", title: t("character.sprite.deleteVoice") });
    },
  });

  const spriteUploadMutation = useMutation({
    mutationFn: async ({
      character,
      emotionTags,
      originalName,
      paths,
      saveFirst,
    }: {
      character: Character;
      emotionTags: string;
      originalName?: string;
      paths: string[];
      saveFirst: boolean;
    }) => {
      const saved = saveFirst ? await saveCharacter(character, originalName) : character;
      return uploadCharacterSprites({
        emotionTags,
        name: saved.name,
        paths,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.uploadImages"),
      });
    },
    onSuccess(character, variables) {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) => {
        const targetNames = new Set([variables.originalName, character.name].filter(Boolean));
        const next = current.filter((item) => !targetNames.has(item.name));
        return [...next, character];
      });
      setIsCreating(false);
      setSelectedName(character.name);
      setDraft((current) => ({
        ...structuredClone(character),
        sprites: mergeSprites(character.sprites, current),
      }));
      setPronunciationText(pronunciationMapToText(character.pronunciation_map));
      setPendingSpritePaths([]);
      showToast({ kind: "success", title: t("character.sprite.uploadImages") });
    },
  });

  const emotionTagsMutation = useMutation({
    mutationFn: (emotionTags: string) => saveCharacterEmotionTags(currentCharacterName, emotionTags),
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
    mutationFn: ({ index, name }: { index: number; name: string }) => deleteCharacterSprite(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("common.remove"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({
        ...current,
        emotion_tags: character.emotion_tags,
        sprites: mergeSprites(character.sprites, current),
      }));
      showToast({ kind: "success", title: t("common.remove") });
    },
  });

  const spriteDeleteAllMutation = useMutation({
    mutationFn: (name: string) => deleteAllCharacterSprites(name),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.clear"),
      });
    },
    onSuccess(character) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({
        ...current,
        emotion_tags: character.emotion_tags,
        sprites: mergeSprites(character.sprites, current),
      }));
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

  /** Merge server sprites while preserving local per-sprite voice_type. */
  const mergeSprites = (serverSprites: Sprite[], current: Character) =>
    serverSprites.map((s, i) => ({ ...s, voice_type: current.sprites[i]?.voice_type ?? s.voice_type }));

  const characterHasGptSovitsModel = (character: Character) =>
    Boolean(character.gpt_model_path?.trim() && character.sovits_model_path?.trim());

  const spriteHasReferenceVoiceText = (sprite: Sprite | undefined) => Boolean(sprite?.voice_text?.trim());

  const defaultSpriteVoiceType = (sprite: Sprite | undefined, character: Character): "preset" | "reference" =>
    characterHasGptSovitsModel(character) && spriteHasReferenceVoiceText(sprite) ? "reference" : "preset";

  const spriteVoiceType = (sprite: Sprite | undefined, character: Character): "preset" | "reference" =>
    sprite?.voice_type ?? defaultSpriteVoiceType(sprite, character);

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

  const buildCharacterSaveInput = () => {
    if (!draft.name.trim()) {
      setNameError(t("character.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return null;
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
      return null;
    }
    return {
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
      originalName: isSavedCharacter ? selectedName : undefined,
    };
  };

  const saveDraft = () => {
    const input = buildCharacterSaveInput();
    if (!input) {
      return;
    }
    saveMutation.mutate(input);
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
  const characterSectionNavItems = [
    { id: "character-basic", label: t("character.section.basic") },
    { id: "character-personality", label: t("character.section.personality") },
    { id: "character-voice", label: t("character.section.voice") },
    { id: "character-sprites", label: t("character.section.sprites") },
    { id: "character-memory", label: t("character.memory.section") },
  ];

  const confirmPendingResourceDelete = async () => {
    if (!pendingResourceDelete) {
      return;
    }
    const target = pendingResourceDelete;
    setPendingResourceDelete(null);
    if (target.kind === "memory") {
      if (!(await ensureMem0Ready())) return;
      memoryDeleteMutation.mutate({ memoryId: target.memoryId, name: target.characterName });
      return;
    }
    if (target.kind === "sprite") {
      spriteDeleteMutation.mutate({ index: target.index, name: target.characterName });
      return;
    }
    if (target.kind === "all-sprites") {
      spriteDeleteAllMutation.mutate(target.characterName);
      return;
    }
    voiceDeleteMutation.mutate({ index: target.index, name: target.characterName });
  };

  const pendingResourceDeleteCopy = pendingResourceDelete
    ? {
        body:
          pendingResourceDelete.kind === "memory"
            ? t("character.memory.deleteConfirmBody", {
                memory: pendingResourceDelete.memory,
                name: pendingResourceDelete.characterName,
              })
            : pendingResourceDelete.kind === "sprite"
              ? t("character.sprite.deleteConfirmBody", {
                  filename: pendingResourceDelete.filename,
                  index: pendingResourceDelete.index + 1,
                  name: pendingResourceDelete.characterName,
                })
              : pendingResourceDelete.kind === "all-sprites"
                ? t("character.sprite.clearConfirmBody", {
                    count: pendingResourceDelete.count,
                    name: pendingResourceDelete.characterName,
                  })
                : t("character.sprite.deleteVoiceConfirmBody", {
                    filename: pendingResourceDelete.filename,
                    index: pendingResourceDelete.index + 1,
                  }),
        confirmLabel:
          pendingResourceDelete.kind === "sprite" || pendingResourceDelete.kind === "sprite-voice"
            ? t("common.remove")
            : t("common.delete"),
        title:
          pendingResourceDelete.kind === "memory"
            ? t("character.memory.delete")
            : pendingResourceDelete.kind === "all-sprites"
              ? t("character.sprite.clear")
              : pendingResourceDelete.kind === "sprite-voice"
                ? t("character.sprite.deleteVoice")
                : t("common.remove"),
      }
    : null;

  const selectExistingCharacter = (name: string) => {
    setIsCreating(false);
    setSelectedName(name);
  };

  const startCreatingCharacter = () => {
    setIsCreating(true);
    setSelectedName("");
    setDraft(createCharacter());
    setPronunciationText("");
    setPendingSpritePaths([]);
    setPendingVoicePaths({});
    setSelectedSpriteIndex(0);
    setNameError("");
  };

  const exportCurrentCharacter = () => {
    if (!currentCharacterName) {
      showToast({
        kind: "error",
        message: t("character.validation.nameRequired"),
        title: t("common.export"),
      });
      return;
    }
    exportMutation.mutate(currentCharacterName);
  };

  const requestCharacterDelete = () => {
    if (!currentCharacterName) {
      showToast({
        kind: "error",
        message: t("character.validation.nameRequired"),
        title: t("common.delete"),
      });
      return;
    }
    setPendingDelete(currentCharacterName);
  };

  const generateSetting = () => {
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
  };

  const translateDraft = () => {
    if (!draft.name.trim() && !draft.character_setting.trim() && !draft.emotion_tags.trim()) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    translateMutation.mutate();
  };

  const uploadSprites = () => {
    if (!pendingSpritePaths.length) {
      showToast({ kind: "error", title: t("character.sprite.selectImages") });
      return;
    }
    const input = buildCharacterSaveInput();
    if (!input) {
      return;
    }
    spriteUploadMutation.mutate({
      ...input,
      emotionTags: input.character.emotion_tags,
      paths: pendingSpritePaths,
      saveFirst: !isSavedCharacter || input.character.name !== currentCharacterName,
    });
  };

  const requestClearSprites = () => {
    if (!isSavedCharacter || !draft.sprites.length) {
      showToast({ kind: "error", title: t("character.sprite.clear") });
      return;
    }
    setPendingResourceDelete({
      characterName: currentCharacterName,
      count: draft.sprites.length,
      kind: "all-sprites",
    });
  };

  const saveSpriteScaleValue = () => {
    if (!isSavedCharacter) {
      showToast({
        kind: "error",
        message: t("character.validation.nameRequired"),
        title: t("character.sprite.saveScale"),
      });
      return;
    }
    spriteScaleMutation.mutate();
  };

  const saveSpriteTags = () => {
    if (!isSavedCharacter || !draft.emotion_tags) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("character.sprite.saveTags"),
      });
      return;
    }
    emotionTagsMutation.mutate(draft.emotion_tags);
  };

  const updatePendingVoicePath = (path: string) => {
    setPendingVoicePaths((current) => ({ ...current, [selectedSpriteIndex]: path }));
  };

  const saveSelectedSpriteVoiceText = (text: string) => {
    const savedText = selected?.sprites[selectedSpriteIndex]?.voice_text ?? "";
    if (currentCharacterName && text !== savedText && !voiceTextMutation.isPending) {
      voiceTextMutation.mutate({ index: selectedSpriteIndex, text });
    }
  };

  const handleSpriteVoiceTypeChange = (value: "preset" | "reference") => {
    updateSprite(selectedSpriteIndex, { voice_type: value });
    if (isSavedCharacter) {
      voiceTypeMutation.mutate({ index: selectedSpriteIndex, voiceType: value });
    }
  };

  const uploadSelectedSpriteVoice = () => {
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
      voiceText: selectedSprite?.voice_text ?? "",
    });
  };

  const requestSelectedSpriteVoiceDelete = () => {
    if (!currentCharacterName || !selectedSprite?.voice_path) {
      showToast({ kind: "error", title: t("character.sprite.deleteVoice") });
      return;
    }
    setPendingResourceDelete({
      characterName: currentCharacterName,
      filename: baseName(selectedSprite.path) || `${selectedSpriteIndex + 1}`,
      index: selectedSpriteIndex,
      kind: "sprite-voice",
    });
  };

  const requestSelectedSpriteDelete = () => {
    if (!currentCharacterName || !selectedSprite) {
      showToast({ kind: "error", title: t("common.remove") });
      return;
    }
    setPendingResourceDelete({
      characterName: currentCharacterName,
      filename: baseName(selectedSprite.path) || `${selectedSpriteIndex + 1}`,
      index: selectedSpriteIndex,
      kind: "sprite",
    });
  };

  const requestMemoryDelete = (memory: { id: string; memory: string }) => {
    setPendingResourceDelete({
      characterName: memoryName,
      kind: "memory",
      memory: memory.memory,
      memoryId: memory.id,
    });
  };

  const confirmBulkSpriteTags = () => {
    const nextTags = bulkSpriteTagsDraft;
    update("emotion_tags", nextTags);
    setBulkSpriteTagsOpen(false);
    if (isSavedCharacter && nextTags.trim() && !emotionTagsMutation.isPending) {
      emotionTagsMutation.mutate(nextTags);
    }
  };

  return (
    <div className="page character-page">
      <CharacterPageHeader
        characters={data}
        exportPending={exportMutation.isPending}
        importPending={importMutation.isPending}
        isCreating={isCreating}
        isLoading={isLoading}
        onCreate={startCreatingCharacter}
        onExport={exportCurrentCharacter}
        onImport={(items) => importMutation.mutate(items)}
        onSave={saveDraft}
        onSelectCharacter={selectExistingCharacter}
        savePending={saveMutation.isPending}
        sectionNav={<PageSectionNav ariaLabel={t("character.title")} items={characterSectionNavItems} />}
        selectedName={selectedName}
      />

      <div className="settings-grid character-page__content">
        <div className="character-page__top-grid">
          <CharacterBasicSection
            colorPickerValue={colorPickerValue}
            draft={draft}
            id="character-basic"
            nameError={nameError}
            onChange={update}
            onColorInputRef={setColorInputElement}
            onDelete={requestCharacterDelete}
            onPickColor={openColorPicker}
            onPronunciationTextChange={setPronunciationText}
            pronunciationText={pronunciationText}
          />

          <CharacterPersonalitySection
            aiPending={aiSettingMutation.isPending}
            draft={draft}
            id="character-personality"
            onAiWrite={generateSetting}
            onChange={update}
            onTranslate={translateDraft}
            translatePending={translateMutation.isPending}
          />
        </div>

        <CharacterVoiceSection
          draft={draft}
          id="character-voice"
          onChange={update}
          voiceReferenceReadOnly={voiceReferenceReadOnly}
        />

        <CharacterSpritesSection
          draft={draft}
          emotionTagsPending={emotionTagsMutation.isPending}
          id="character-sprites"
          onClearSprites={requestClearSprites}
          onOpenBulkTags={openBulkSpriteTagsDialog}
          onPendingSpritePathsChange={setPendingSpritePaths}
          onPendingVoicePathChange={updatePendingVoicePath}
          onSaveScale={saveSpriteScaleValue}
          onSaveTags={saveSpriteTags}
          onScaleChange={update}
          onScaleWheel={handleSpriteScaleWheel}
          onSelectSprite={setSelectedSpriteIndex}
          onSpriteDelete={requestSelectedSpriteDelete}
          onSpriteTagChange={(value) => updateSpriteTag(selectedSpriteIndex, value)}
          onSpriteUpload={uploadSprites}
          onSpriteVoiceDelete={requestSelectedSpriteVoiceDelete}
          onSpriteVoiceTextBlur={saveSelectedSpriteVoiceText}
          onSpriteVoiceTextChange={(value) => updateSprite(selectedSpriteIndex, { voice_text: value })}
          onSpriteVoiceUpload={uploadSelectedSpriteVoice}
          onSpriteVoiceTypeChange={handleSpriteVoiceTypeChange}
          pendingSpritePaths={pendingSpritePaths}
          pendingVoicePath={pendingVoicePaths[selectedSpriteIndex] ?? ""}
          selectedSprite={
            selectedSprite ? { ...selectedSprite, voice_type: spriteVoiceType(selectedSprite, draft) } : undefined
          }
          selectedSpriteIndex={selectedSpriteIndex}
          selectedSpriteTag={selectedSpriteTag}
          spriteDeletePending={spriteDeleteMutation.isPending}
          spriteGalleryItems={spriteGalleryItems}
          spriteScalePending={spriteScaleMutation.isPending}
          spriteUploadPending={spriteUploadMutation.isPending}
          voiceDeletePending={voiceDeleteMutation.isPending}
          voiceUploadPending={voiceUploadMutation.isPending}
        />

        <CharacterMemorySection
          addPending={memoryAddMutation.isPending}
          data={memoryDepError ? undefined : memoryQuery.data}
          deletePending={memoryDeleteMutation.isPending}
          depError={memoryDepError}
          depInstalling={memoryDepInstalling}
          error={memoryQuery.error}
          id="character-memory"
          isChecking={mem0Checking}
          isError={memoryQuery.isError || !!memoryDepError}
          isFetched={memoryQuery.isFetched}
          isFetching={memoryQuery.isFetching}
          isLoading={memoryQuery.isLoading}
          memoryInput={memoryInput}
          memoryName={memoryName}
          onAddMemory={() => void addMemory()}
          onDeleteMemory={requestMemoryDelete}
          onInstallDep={() => void installMemoryDep()}
          onMemoryInputChange={setMemoryInput}
          onRefresh={() => void refreshMemories()}
        />
      </div>

      <SpriteTagsDialog
        draft={bulkSpriteTagsDraft}
        onChange={setBulkSpriteTagsDraft}
        onClose={() => setBulkSpriteTagsOpen(false)}
        onConfirm={confirmBulkSpriteTags}
        open={bulkSpriteTagsOpen}
      />

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
      <AlertDialog
        body={pendingResourceDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={pendingResourceDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={() => setPendingResourceDelete(null)}
        onConfirm={confirmPendingResourceDelete}
        open={Boolean(pendingResourceDelete)}
        title={pendingResourceDeleteCopy?.title ?? t("common.delete")}
      />

      <Dialog
        closeLabel={t("common.close")}
        footer={
          memoryDepInstalling ? (
            <Button disabled>{t("character.memory.depInstalling")}</Button>
          ) : (
            <Button
              onClick={() => {
                setMemoryDepOpen(false);
                setMemoryDepTask(null);
              }}
            >
              {t("common.close")}
            </Button>
          )
        }
        onClose={() => {
          if (!memoryDepInstalling) {
            setMemoryDepOpen(false);
            setMemoryDepTask(null);
          }
        }}
        open={memoryDepOpen}
        title={t("character.memory.depMissingTitle")}
      >
        <div className="memory-dep-dialog">
          <p>{t("character.memory.depMissingBody")}</p>
          {memoryDepTask ? (
            <TaskProgress logLimit={6} task={memoryDepTask} />
          ) : (
            <p className="inline-status">{t("character.memory.depInstalling")}</p>
          )}
        </div>
      </Dialog>

      <Dialog
        closeLabel={t("common.close")}
        footer={<Button onClick={() => setMem0LoadingOpen(false)}>{t("common.cancel")}</Button>}
        onClose={() => setMem0LoadingOpen(false)}
        open={mem0LoadingOpen}
        title={t("character.memory.section")}
      >
        <div className="memory-dep-dialog">
          <p>{mem0LoadingMessage}</p>
          <span className="memory-dep-progress" role="progressbar" />
        </div>
      </Dialog>
    </div>
  );
}
