import { numberedTags, tagContents } from "../../assets/assetText";
import { createAgentPreviewPlatform } from "../agentPreviewPlatform";
import { createChatPreviewPlatform } from "../slices/chatPreviewPlatform";
import { createKnowledgePreviewPlatform } from "../slices/knowledgePreviewPlatform";
import { createPerceptionPreviewPlatform } from "../slices/perceptionPreviewPlatform";
import { createMcpPreviewPlatform, createPluginsPreviewPlatform } from "../slices/pluginPreviewPlatform";
import { clone, createBrowserPreviewContext, delay } from "../slices/previewContext";
import {
  createAvatarRuntimesPreviewPlatform,
  createCharacterRelationPreviewPlatform,
  createCharactersPreviewPlatform,
} from "../slices/characterPreviewPlatform";
import {
  createConfigPreviewPlatform,
  createModelAssetsPreviewPlatform,
  createMusicCoverPreviewPlatform,
  createRuntimePreviewPlatform,
} from "../slices/configPreviewPlatform";
import {
  createBackgroundsPreviewPlatform,
  createEffectsPreviewPlatform,
  createFilesPreviewPlatform,
  createLogsPreviewPlatform,
  createTasksPreviewPlatform,
  createTemplatesPreviewPlatform,
  createToolsPreviewPlatform,
} from "../slices/workspacePreviewPlatform";
import { createStoryPreviewPlatform } from "../storyPreviewPlatform";
import type { Character } from "../slices/characterTypes";
import type {
  CharacterOutfitState,
  ChatCommand,
  ChatCommandResult,
  ChatHistoryEntry,
  ChatLaunchPayload,
  ChatOption,
  ChatPlatform,
  ChatReplaySnapshot,
  ChatSendPayload,
  ChatSnapshot,
  ChatSprite,
  ChatStageEvent,
} from "../slices/chatTypes";
import type { ApiConfig, AppConfig, SystemConfig } from "../slices/configTypes";
import type { TemplateLaunchSession, TemplateSummary, UserPromptPresetLibrary } from "../slices/workspaceTypes";
import type { ShinsekaiPlatform } from "../types";
import { getPlatform } from "../platform";
import { isStandaloneRuntimeActive, type RuntimeTarget } from "../runtimeTarget";
import { sampleConfig } from "../sampleData";
import { buildStandaloneAdapterCatalog, resolveLlmAdapter } from "./ai/adapters/registry";
import { getLlmProviderPreset } from "./ai/adapters/llm/presets";
import { standaloneHttpJson, standaloneHttpRequest } from "./ai/httpClient";
import { StandaloneChatTurnDriver } from "./ai/standaloneChatTurn";
import { exportCharPackage, importCharPackage, refreshCharacterMouthManifestUrls } from "./packages/charPackageCodec";
import { characterNameKey, generateStandaloneTemplateSummary } from "./ai/templateGenerator";
import {
  loadBundledPresets,
  resolveBundledStarterAssetUrl,
  upgradeStarterPresetsInPlace,
} from "./packages/presetLoader";
import { getKvConfig, setKvConfig } from "./storage/indexedDbStore";
import {
  generateSecureRandomToken,
  StandaloneSessionStore,
  type StandaloneSessionRecord,
} from "./storage/sessionStore";
import {
  getVfsBlobAsync,
  hydrateVfsBlobs,
  isVfsPath,
  normalizeVfsPath,
  putVfsBlob,
  relocateVfsBlob,
  resolveVfsUrl,
  stageUploadedFiles,
  VFS_SCHEME,
} from "./storage/vfsBlobRegistry";
import { ToyCloudCheckpointBridge } from "./toy/toySdkBridge";

const KV_APP_CONFIG = "app_config";
const KV_TEMPLATES = "templates";
const KV_TEMPLATE_SESSION = "template_session";
const KV_USER_PROMPT_PRESETS = "user_prompt_presets";
const KV_ACTIVE_SESSION_ID = "active_session_id";
const KV_ACTIVE_THEME_ID = "active_theme_id";

function normalizeRemoteUrl(rawUrl: string): string {
  return rawUrl.trim().replace(/\/+$/, "");
}

function remoteHeaders(token?: string): Record<string, string> {
  const trimmed = token?.trim() ?? "";
  return trimmed ? { "X-Shinsekai-Bridge-Token": trimmed } : {};
}

export async function testRemotePcBridge(input: {
  bridgeUrl: string;
  token?: string;
}): Promise<{ ok: boolean; characterCount: number; message: string }> {
  const baseUrl = normalizeRemoteUrl(input.bridgeUrl);
  if (!baseUrl) {
    throw new Error("请填写电脑端 Shinsekai 地址，例如 http://192.168.1.100:8787");
  }
  const { data } = await standaloneHttpJson<AppConfig>({
    url: `${baseUrl}/api/config`,
    method: "GET",
    headers: remoteHeaders(input.token),
    timeoutMs: 8000,
  });
  const chars = Array.isArray(data.characters) ? data.characters.length : 0;
  return {
    ok: true,
    characterCount: chars,
    message: `已连接电脑端（共 ${chars} 个角色）`,
  };
}

export async function listRemotePcCharacters(input: { bridgeUrl: string; token?: string }): Promise<Character[]> {
  const baseUrl = normalizeRemoteUrl(input.bridgeUrl);
  const { data } = await standaloneHttpJson<AppConfig>({
    url: `${baseUrl}/api/config`,
    method: "GET",
    headers: remoteHeaders(input.token),
    timeoutMs: 10000,
  });
  return Array.isArray(data.characters) ? data.characters : [];
}

export async function syncCharacterFromRemotePc(input: {
  bridgeUrl: string;
  token?: string;
  characterName: string;
}): Promise<Character[]> {
  const baseUrl = normalizeRemoteUrl(input.bridgeUrl);
  const { data: exportRes } = await standaloneHttpJson<{ path: string }>({
    url: `${baseUrl}/api/characters/export`,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...remoteHeaders(input.token),
    },
    body: JSON.stringify({ name: input.characterName }),
    timeoutMs: 30_000,
  });

  if (!exportRes.path) {
    throw new Error(`电脑端未能导出角色「${input.characterName}」`);
  }

  const downloadResp = await standaloneHttpRequest({
    url: `${baseUrl}/api/download?path=${encodeURIComponent(exportRes.path)}`,
    method: "GET",
    headers: remoteHeaders(input.token),
    timeoutMs: 60_000,
  });
  if (!downloadResp.ok || downloadResp.body.byteLength < 64) {
    throw new Error(`下载角色包失败 (HTTP ${downloadResp.status})`);
  }

  const safeCopy = new Uint8Array(downloadResp.body.byteLength);
  safeCopy.set(downloadResp.body);
  const packageFile: File =
    typeof File !== "undefined"
      ? new File([safeCopy], `${sanitizeVfsFileName(input.characterName || "character")}.char`, {
          type: "application/zip",
        })
      : (new Blob([safeCopy], { type: "application/zip" }) as unknown as File);

  if (isStandaloneRuntimeActive()) {
    return await getPlatform().characters.import([packageFile]);
  }

  await hydrateVfsBlobs();
  let savedConfig = await getKvConfig<AppConfig>(KV_APP_CONFIG);
  if (!savedConfig) {
    const presets = await loadBundledPresets([]);
    savedConfig = {
      ...clone(sampleConfig),
      api_config: defaultStandaloneApiConfig(sampleConfig.api_config),
      characters: presets.characters,
      background_list: presets.backgrounds,
    };
  }
  const existingChars = Array.isArray(savedConfig.characters) ? savedConfig.characters : [];
  const imported = await importCharPackage(packageFile, existingChars);
  savedConfig.characters = [...existingChars, ...imported];
  await setKvConfig(KV_APP_CONFIG, savedConfig);
  return imported;
}

function defaultStandaloneApiConfig(base: ApiConfig): ApiConfig {
  return {
    ...clone(base),
    llm_provider: "硅基流动",
    tts_provider: "openai-speech",
    llm_base_url: "https://api.siliconflow.cn/v1",
    llm_base_urls: {
      ...base.llm_base_urls,
      硅基流动: "https://api.siliconflow.cn/v1",
      Moonshot: "https://api.moonshot.cn/v1",
      OpenRouter: "https://openrouter.ai/api/v1",
    },
    llm_model: {
      ...base.llm_model,
      硅基流动: "deepseek-ai/DeepSeek-V3",
      Deepseek: "deepseek-chat",
      ChatGPT: "gpt-4o-mini",
      通义千问: "qwen-plus",
    },
    max_context_tokens: base.max_context_tokens || 32000,
    compact_threshold: base.compact_threshold || 0.4,
    compact_target_ratio: base.compact_target_ratio || 0.3,
    history_recent_messages: base.history_recent_messages || 20,
    tts_extra_configs: {
      ...base.tts_extra_configs,
      "openai-speech": {
        reuse_llm_key: true,
        api_key: "",
        base_api_url: "https://api.siliconflow.cn/v1",
        model: "FunAudioLLM/CosyVoice2-0.5B",
        default_voice_id: "FunAudioLLM/CosyVoice2-0.5B:claire",
        enable_zero_shot: true,
        response_format: "mp3",
      },
    },
  };
}

function buildOutfitStateMap(
  characters: Character[],
  initialOutfits?: ChatLaunchPayload["initialOutfits"],
): Record<string, CharacterOutfitState> {
  const outfits: Record<string, CharacterOutfitState> = {};
  for (const char of characters) {
    const requested = initialOutfits?.[char.name];
    const requestedGroup = typeof requested === "string" ? requested : requested?.activeGroup;
    const activeGroup = requestedGroup || char.default_sprite_group || char.sprite_groups?.[0] || "";
    if (!activeGroup) continue;
    outfits[char.name] = {
      characterName: char.name,
      activeGroup,
      locked: typeof requested === "object" ? Boolean(requested.locked) : false,
      updatedAtMs: Date.now(),
    };
  }
  return outfits;
}

function extractCommandText(payload: unknown): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return String(payload ?? "").trim();
  }
  const candidate = payload as Partial<ChatSendPayload>;
  const text = String(candidate.text ?? "").trim();
  const labels = Array.isArray(candidate.attachments)
    ? candidate.attachments
        .filter((item) => item?.kind === "image" || item?.kind === "file")
        .map((item) => `[${item.kind}: ${String(item.name || "附件")}]`)
    : [];
  return [text, labels.join(" ")].filter(Boolean).join("\n");
}

function sanitizeVfsFileName(raw: string): string {
  const clean = raw.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_").trim();
  return clean || "asset.bin";
}

function extractAssetFileName(rawPath: string): string {
  const clean = rawPath.replace(/\\/g, "/").split(/[?#]/)[0];
  const base = sanitizeVfsFileName(clean.split("/").filter(Boolean).pop() || "asset.bin");
  return base.replace(/^\d{13}-\d+-/, "") || base;
}

function allocateUniqueVfsPath(targetDirVfsPrefix: string, fileName: string, usedPaths: Set<string>): string {
  const cleanPrefix = targetDirVfsPrefix.replace(/\/+$/, "");
  const dotIdx = fileName.lastIndexOf(".");
  const stem = dotIdx > 0 ? fileName.slice(0, dotIdx) : fileName;
  const ext = dotIdx > 0 ? fileName.slice(dotIdx) : "";
  let candidate = `${cleanPrefix}/${fileName}`;
  let counter = 1;
  while (usedPaths.has(candidate)) {
    candidate = `${cleanPrefix}/${stem}-${counter}${ext}`;
    counter += 1;
  }
  usedPaths.add(candidate);
  return candidate;
}

async function relocatePathsList(
  rawPaths: string[],
  targetDirVfsPrefix: string,
  existingPaths: string[] = [],
): Promise<string[]> {
  const usedPaths = new Set(existingPaths);
  const relocated: string[] = [];
  for (const rawPath of rawPaths) {
    if (!rawPath || !isVfsPath(rawPath)) {
      relocated.push(rawPath);
      continue;
    }
    const normalized = normalizeVfsPath(rawPath);
    if (!normalized.startsWith(`${VFS_SCHEME}uploads/`)) {
      usedPaths.add(normalized);
      relocated.push(normalized);
      continue;
    }
    const targetPath = allocateUniqueVfsPath(targetDirVfsPrefix, extractAssetFileName(normalized), usedPaths);
    relocated.push(await relocateVfsBlob(normalized, targetPath));
  }
  return relocated;
}

export function createStandalonePlatform(options?: { target?: RuntimeTarget }): ShinsekaiPlatform {
  const target: RuntimeTarget = options?.target ?? "web";
  const ctx = createBrowserPreviewContext();
  const sessionStore = new StandaloneSessionStore();
  const toyBridge = new ToyCloudCheckpointBridge();

  ctx.config.adapter_catalog = buildStandaloneAdapterCatalog(target);

  let initPromise: Promise<void> | null = null;
  let activeSessionId: string | null = null;
  let explicitlyClosed = false;
  let latestUserInputDraft = "";

  const baseCharacters = createCharactersPreviewPlatform(ctx);
  const baseRelation = createCharacterRelationPreviewPlatform(ctx);
  const baseBackgrounds = createBackgroundsPreviewPlatform(ctx);
  const baseEffects = createEffectsPreviewPlatform(ctx);
  const baseChat = createChatPreviewPlatform(ctx);
  const baseConfig = createConfigPreviewPlatform(ctx);
  const baseTemplates = createTemplatesPreviewPlatform(ctx);
  const baseFiles = createFilesPreviewPlatform(ctx);

  const resolveStandaloneFileUrl = (path: string): string => {
    if (!path) return "";
    const starterAsset = resolveBundledStarterAssetUrl(path);
    if (starterAsset) return starterAsset;
    if (isVfsPath(path)) return resolveVfsUrl(path);
    return baseFiles.fileUrl(path);
  };

  const nextSeq = () => ctx.nextChatEventSeq();

  const emitStandaloneChat = () => {
    const seq = nextSeq();
    const stampedTs = Date.now();
    const updated: ChatSnapshot = {
      ...ctx.getChat(),
      eventSeq: seq,
      serverTimeMs: stampedTs,
    };
    ctx.setChat(updated);
    const snapshot = clone(updated);
    for (const listener of ctx.chatListeners) {
      listener(clone(snapshot));
    }
    const event: ChatStageEvent = {
      v: 1,
      seq,
      ts: stampedTs,
      type: "snapshot",
      snapshot,
    };
    for (const listener of ctx.chatEventListeners) {
      listener(clone(event));
    }
  };

  const emitStageEvent = (event: ChatStageEvent) => {
    const seq = event.seq > 0 ? event.seq : nextSeq();
    const stampedTs = event.ts || Date.now();
    const currentChat = ctx.getChat();
    if ((currentChat.eventSeq ?? 0) < seq) {
      ctx.setChat({
        ...currentChat,
        eventSeq: seq,
        serverTimeMs: stampedTs,
      });
    }
    const stamped = clone({
      ...event,
      seq,
      ts: stampedTs,
    });
    for (const listener of ctx.chatEventListeners) {
      listener(stamped);
    }
  };

  const persistAppConfig = async () => {
    ctx.config.adapter_catalog = buildStandaloneAdapterCatalog(target);
    await setKvConfig(KV_APP_CONFIG, clone(ctx.config));
  };

  const persistTemplates = async () => {
    await setKvConfig(KV_TEMPLATES, clone(ctx.getTemplates()));
  };

  const persistTemplateSession = async () => {
    await setKvConfig(KV_TEMPLATE_SESSION, clone(ctx.getTemplateSession()));
  };

  const persistUserPromptPresets = async () => {
    await setKvConfig(KV_USER_PROMPT_PRESETS, clone(ctx.getUserPromptPresets()));
  };

  const turnDriver = new StandaloneChatTurnDriver({
    getApiConfig: () => ctx.config.api_config,
    getCharacters: () => ctx.config.characters,
    getBackgrounds: () => ctx.config.background_list,
    getEffects: () => ctx.config.effect_list,
    getSystemConfig: () => ctx.config.system_config,
    getChat: () => ctx.getChat(),
    setChat: (next) => ctx.setChat(next),
    emitChat: emitStandaloneChat,
    emitStageEvent,
    nextEventSeq: nextSeq,
    sessionStore,
    httpClient: standaloneHttpRequest,
    resolveFileUrl: resolveStandaloneFileUrl,
    onProgressCheckpoint: () => {
      if (target !== "toy" || !activeSessionId) return;
      const session = sessionStore.getSession(activeSessionId);
      const chat = ctx.getChat();
      if (!session) return;
      toyBridge.scheduleCheckpointSync({
        v: 1,
        characterName: session.characters[0] ?? chat.characterName ?? "",
        prologueCompleted: Boolean(session.prologueCompleted),
        prologueStepId: session.prologueStepId ?? "intro_0",
        statsSummary: (chat.stats ?? []).slice(0, 6).map((s) => ({
          label: s.label,
          value: s.value,
          ...(s.max !== undefined ? { max: s.max } : {}),
        })),
        updatedAtMs: Date.now(),
      });
    },
  });

  if (target === "toy") {
    toyBridge.bindVisibilityFlush(() => {
      if (!activeSessionId) return null;
      const session = sessionStore.getSession(activeSessionId);
      if (!session) return null;
      const chat = ctx.getChat();
      return {
        v: 1,
        characterName: session.characters[0] ?? chat.characterName ?? "",
        prologueCompleted: Boolean(session.prologueCompleted),
        prologueStepId: session.prologueStepId ?? "intro_0",
        statsSummary: (chat.stats ?? []).slice(0, 6).map((s) => ({
          label: s.label,
          value: s.value,
          ...(s.max !== undefined ? { max: s.max } : {}),
        })),
        updatedAtMs: Date.now(),
      };
    });
  }

  const ensureInitialized = async () => {
    if (initPromise) return initPromise;
    initPromise = (async () => {
      await Promise.all([hydrateVfsBlobs(), sessionStore.hydrate()]);

      const [savedConfig, savedTemplates, savedTemplateSession, savedUserPromptPresets, savedSessionId, savedThemeId] =
        await Promise.all([
          getKvConfig<AppConfig>(KV_APP_CONFIG),
          getKvConfig<TemplateSummary[]>(KV_TEMPLATES),
          getKvConfig<TemplateLaunchSession | null>(KV_TEMPLATE_SESSION),
          getKvConfig<UserPromptPresetLibrary | null>(KV_USER_PROMPT_PRESETS),
          getKvConfig<string>(KV_ACTIVE_SESSION_ID),
          getKvConfig<string>(KV_ACTIVE_THEME_ID),
        ]);

      if (savedConfig) {
        const mergedApi: ApiConfig = {
          ...defaultStandaloneApiConfig(ctx.config.api_config),
          ...savedConfig.api_config,
          llm_api_key: { ...(savedConfig.api_config?.llm_api_key ?? {}) },
          llm_base_urls: {
            ...defaultStandaloneApiConfig(ctx.config.api_config).llm_base_urls,
            ...(savedConfig.api_config?.llm_base_urls ?? {}),
          },
          llm_model: {
            ...defaultStandaloneApiConfig(ctx.config.api_config).llm_model,
            ...(savedConfig.api_config?.llm_model ?? {}),
          },
          tts_extra_configs: {
            ...defaultStandaloneApiConfig(ctx.config.api_config).tts_extra_configs,
            ...(savedConfig.api_config?.tts_extra_configs ?? {}),
          },
        };
        ctx.config.api_config = mergedApi;
        ctx.config.system_config = { ...ctx.config.system_config, ...savedConfig.system_config };
        ctx.config.characters = Array.isArray(savedConfig.characters) ? savedConfig.characters : [];
        ctx.config.background_list = Array.isArray(savedConfig.background_list) ? savedConfig.background_list : [];
        ctx.config.effect_list = Array.isArray(savedConfig.effect_list) ? savedConfig.effect_list : [];

        if (!ctx.config.characters.length) {
          const presets = await loadBundledPresets([]);
          ctx.config.characters = presets.characters;
          if (!ctx.config.background_list.length) {
            ctx.config.background_list = presets.backgrounds;
          }
          await persistAppConfig();
        } else {
          const upgradedStarter = upgradeStarterPresetsInPlace(ctx.config.characters, ctx.config.background_list);
          if (upgradedStarter) {
            await persistAppConfig();
          }
          await refreshCharacterMouthManifestUrls(ctx.config.characters);
        }
      } else {
        const presets = await loadBundledPresets([]);
        ctx.config.api_config = defaultStandaloneApiConfig(ctx.config.api_config);
        ctx.config.characters = presets.characters;
        ctx.config.background_list = presets.backgrounds;
        await persistAppConfig();
      }

      if (savedUserPromptPresets && typeof savedUserPromptPresets === "object") {
        ctx.setUserPromptPresets({
          groups: Array.isArray(savedUserPromptPresets.groups) ? savedUserPromptPresets.groups : [],
          presets: Array.isArray(savedUserPromptPresets.presets) ? savedUserPromptPresets.presets : [],
        });
      }
      if (savedTemplateSession) {
        ctx.setTemplateSession(savedTemplateSession);
      }
      if (Array.isArray(savedTemplates) && savedTemplates.length) {
        ctx.setTemplates(savedTemplates);
      } else {
        const starterChar = ctx.config.characters[0]?.name ?? "星奈";
        const starterBg = ctx.config.background_list[0]?.name ?? "星海观测台";
        const currentTemplates = ctx.getTemplates();
        if (currentTemplates.length) {
          const starterScenario = "在星海观测台展开温柔又轻松的互动对话。";
          let starterSystem = currentTemplates[0].system ?? "";
          let starterContent = currentTemplates[0].content ?? "";
          try {
            const generated = generateStandaloneTemplateSummary(
              {
                name: `${starterChar} 的观测台`,
                scenario: starterScenario,
                characters: ctx.config.characters.length ? [starterChar] : [],
                backgroundName: starterBg,
                voiceLanguage: ctx.config.system_config.voice_language,
              },
              ctx.config,
            );
            starterSystem = generated.system ?? "";
            starterContent = generated.content;
          } catch {
            // Fall back to existing starter system prompt when cast is unavailable.
          }
          ctx.setTemplates([
            {
              ...currentTemplates[0],
              id: currentTemplates[0].id || "starter-template",
              name: `${starterChar} 的观测台`,
              scenario: starterScenario,
              system: starterSystem,
              content: starterContent,
            },
          ]);
        }
        if (!savedTemplateSession) {
          ctx.setTemplateSession({
            allowPlayerDialogue: false,
            autoOutfitSwitch: true,
            background: starterBg,
            characterPromptMode: "compact",
            effectNames: [],
            filenameStub: "starter",
            historyPath: "./data/history/starter.json",
            initSpritePath: "",
            maxDialogItems: 4,
            maxSpeechChars: 120,
            mediaSelectionMode: "indexed",
            memoryMode: "isolated",
            playerCharacter: "旅人",
            primaryCharacters: [starterChar],
            readPlayerSpeech: false,
            roomId: "",
            scenario: "",
            selectedCharacters: [starterChar],
            showInitialSprite: true,
            system: "",
            templateFileDropdown: "",
            useCg: false,
            useChoice: true,
            useCot: false,
            useEffect: false,
            useNarration: true,
            useStat: true,
            useTranslation: false,
            voiceLanguage: "Chinese",
          });
        }
      }

      if (savedThemeId) {
        ctx.setActiveThemeId(savedThemeId);
      }

      if (savedSessionId && sessionStore.getSession(savedSessionId)) {
        activeSessionId = savedSessionId;
      } else {
        const allSessions = sessionStore.listSessions();
        if (allSessions.length) {
          activeSessionId = allSessions[0].sessionId;
        }
      }
    })();

    return initPromise;
  };

  const applySessionToSnapshot = (session: StandaloneSessionRecord, running = true): ChatSnapshot => {
    const selectedChars = session.characters.length
      ? ctx.config.characters.filter((c) => session.characters.includes(c.name))
      : ctx.config.characters.slice(0, 1);
    const activeBg =
      ctx.config.background_list.find((b) => b.name === session.payload.backgroundName) ??
      ctx.config.background_list[0];
    const bgUrl = activeBg?.sprites?.[0]?.path ? resolveStandaloneFileUrl(activeBg.sprites[0].path) : "";

    const turns = sessionStore.listTurns(session.sessionId);
    const lastStageTurn = [...turns].reverse().find((t) => t.stageSnapshot);
    const lastSpokenTurn = [...turns].reverse().find((t) => t.role === "assistant" || t.role === "system");
    const lastTurn = turns[turns.length - 1];
    const activeOptions: ChatOption[] =
      lastTurn?.role === "options" && lastTurn.selectedIndex == null && lastTurn.options?.length
        ? lastTurn.options
        : [];

    const initialSprites: ChatSprite[] = selectedChars
      .filter((c) => c.sprites?.length)
      .map((c) => {
        const firstSprite = c.sprites[0];
        return {
          id: `sprite-${c.name}`,
          identityKey: c.name,
          label: c.name,
          path: resolveStandaloneFileUrl(firstSprite.path),
          scale: c.sprite_scale || 1,
          avatarType: c.avatar_type || "static",
          modelUrl: "",
          mouthSync: firstSprite.mouth_sync ? resolveStandaloneFileUrl(firstSprite.mouth_sync) : undefined,
          portraitCrop: firstSprite.portrait_crop ?? c.portrait_crop,
        };
      });

    const historyEntries: ChatHistoryEntry[] = turns
      .filter((node) => node.role !== "options")
      .map((node) => ({
        id: node.turnId,
        role: node.role,
        text: node.speaker && node.role === "assistant" ? `【${node.speaker}】${node.plainText}` : node.plainText,
        createdAt: node.createdAtMs,
        revertUserIndex: node.revertUserIndex,
      }));

    const resolveSnapshotSprite = (sp: ChatSprite): ChatSprite => {
      const matchedChar = selectedChars.find((c) => c.name === sp.label || c.name === sp.identityKey);
      return {
        ...sp,
        path: resolveStandaloneFileUrl(sp.path),
        mouthSync: sp.mouthSync ? resolveStandaloneFileUrl(sp.mouthSync) : undefined,
        modelUrl: sp.modelUrl ? resolveStandaloneFileUrl(sp.modelUrl) : "",
        ...(sp.transitions?.length
          ? {
              transitions: sp.transitions.map((tr) => ({
                ...tr,
                fromUrl: resolveStandaloneFileUrl(tr.fromUrl),
                url: resolveStandaloneFileUrl(tr.url),
              })),
            }
          : {}),
        ...(matchedChar?.sprite_prefix === "starter_hoshina"
          ? { portraitCrop: matchedChar.portrait_crop ?? sp.portraitCrop }
          : {}),
      };
    };

    const nextSnapshot: ChatSnapshot = {
      ...ctx.getChat(),
      eventSeq: nextSeq(),
      serverTimeMs: Date.now(),
      sessionId: session.sessionId,
      historyPath: session.historyPath,
      chatProcessRunning: running,
      chatRuntimeClosing: false,
      status: "idle",
      backgroundPath:
        (lastStageTurn?.stageSnapshot?.backgroundPath
          ? resolveStandaloneFileUrl(lastStageTurn.stageSnapshot.backgroundPath)
          : "") || bgUrl,
      bgmPath: lastStageTurn?.stageSnapshot?.bgmPath
        ? resolveStandaloneFileUrl(lastStageTurn.stageSnapshot.bgmPath)
        : "",
      cgPath: lastStageTurn?.stageSnapshot?.cgPath ? resolveStandaloneFileUrl(lastStageTurn.stageSnapshot.cgPath) : "",
      sprites: lastStageTurn?.stageSnapshot?.sprites?.length
        ? lastStageTurn.stageSnapshot.sprites.map(resolveSnapshotSprite)
        : initialSprites,
      stats: lastStageTurn?.stageSnapshot?.stats?.length ? lastStageTurn.stageSnapshot.stats : session.stats,
      outfits: session.outfits,
      autoOutfitSwitch: session.autoOutfitSwitch,
      characterName: lastSpokenTurn?.speaker ?? selectedChars[0]?.name ?? "",
      dialogText: lastSpokenTurn?.plainText ?? "",
      dialogHtml: "",
      options: activeOptions,
      historyEntries,
      userDisplayName: session.payload.playerCharacter || "我",
      voiceLanguage: session.payload.voiceLanguage || "Chinese",
    };

    ctx.setChat(nextSnapshot);
    return nextSnapshot;
  };

  const launchOrCreateStarterSession = async (payload?: ChatLaunchPayload): Promise<ChatSnapshot> => {
    await ensureInitialized();
    turnDriver.cancelActiveTurn();
    const charName = payload?.characters?.[0] || ctx.config.characters[0]?.name || "星奈";
    const bgName = payload?.backgroundName || ctx.config.background_list[0]?.name || "星海观测台";
    const effectivePayload: ChatLaunchPayload = payload ?? {
      templateId: "starter-template",
      templateName: "星海观测台",
      characters: [charName],
      primaryCharacters: [charName],
      backgroundName: bgName,
      historyPath: "./data/history/starter.json",
      useChoice: true,
      useNarration: true,
      useStat: true,
      playerCharacter: "旅人",
    };

    const selectedChars = ctx.config.characters.filter((c) => effectivePayload.characters.includes(c.name));
    const outfits = buildOutfitStateMap(selectedChars, effectivePayload.initialOutfits);
    const requestedHistoryPath = effectivePayload.historyPath || "./data/history/starter.json";
    let targetHistoryPath = requestedHistoryPath;
    if (effectivePayload.resetHistory) {
      const historyBase = requestedHistoryPath.toLowerCase().endsWith(".json")
        ? requestedHistoryPath.slice(0, -".json".length)
        : requestedHistoryPath;
      targetHistoryPath = `${historyBase}-restart-${Date.now()}-${generateSecureRandomToken(3)}.json`;
      const currentTemplateSession = ctx.getTemplateSession();
      if (currentTemplateSession) {
        ctx.setTemplateSession({
          ...currentTemplateSession,
          historyPath: targetHistoryPath,
        });
        await persistTemplateSession();
      }
    }

    const sessionPayload: ChatLaunchPayload = {
      ...effectivePayload,
      historyPath: targetHistoryPath,
      resetHistory: false,
    };

    const session = await sessionStore.ensureSession({
      historyPath: targetHistoryPath,
      title: effectivePayload.conversationTitle || `${charName}的对话`,
      payload: sessionPayload,
      outfits,
    });

    activeSessionId = session.sessionId;
    explicitlyClosed = false;
    await setKvConfig(KV_ACTIVE_SESSION_ID, session.sessionId);

    const snapshot = applySessionToSnapshot(session, true);
    if (ctx.config.characters.length && sessionStore.listTurns(session.sessionId).length === 0) {
      const lead = selectedChars[0] ?? ctx.config.characters[0];
      await turnDriver.seedInitialPrologue(session.sessionId, lead);
    }
    return applySessionToSnapshot(session, true) || snapshot;
  };

  const chatPlatform: ChatPlatform = {
    async listConversations() {
      await ensureInitialized();
      return sessionStore.listConversationSummaries();
    },
    async getCurrentConversation() {
      await ensureInitialized();
      if (!activeSessionId) return null;
      const summary = sessionStore.listConversationSummaries().find((s) => s.sessionId === activeSessionId);
      return summary ?? null;
    },
    async prepareConversation(id) {
      await ensureInitialized();
      const session = sessionStore.getSession(id) ?? sessionStore.getSessionByHistoryPath(id);
      if (!session) throw new Error("对话不存在");
      return clone(session.payload);
    },
    async reconfigureConversation(id, payload) {
      const session = sessionStore.getSession(id) ?? sessionStore.getSessionByHistoryPath(id);
      if (!session) throw new Error("对话不存在");
      return this.launch({ ...payload, historyPath: session.historyPath, resetHistory: false });
    },
    async renameConversation(id, title) {
      await ensureInitialized();
      const updated = await sessionStore.updateSessionMeta(id, { title });
      if (!updated) throw new Error("对话不存在");
      return sessionStore.listConversationSummaries().find((s) => s.sessionId === id)!;
    },
    async updateConversationSettings(id, input) {
      await ensureInitialized();
      const updated = await sessionStore.updateSessionMeta(id, {
        ...(input.autoOutfitSwitch !== undefined ? { autoOutfitSwitch: input.autoOutfitSwitch } : {}),
        ...(input.memoryMode !== undefined
          ? { payload: { ...sessionStore.getSession(id)!.payload, memoryMode: input.memoryMode } }
          : {}),
      });
      if (!updated) throw new Error("对话不存在");
      return sessionStore.listConversationSummaries().find((s) => s.sessionId === id)!;
    },
    async deleteConversation(id) {
      await ensureInitialized();
      if (activeSessionId === id) {
        activeSessionId = null;
      }
      await sessionStore.deleteSession(id);
    },
    async launch(payload) {
      return launchOrCreateStarterSession(payload);
    },
    async resumeLast() {
      await ensureInitialized();
      explicitlyClosed = false;
      if (activeSessionId) {
        const session = sessionStore.getSession(activeSessionId);
        if (session) {
          return applySessionToSnapshot(session, true);
        }
      }
      const sessions = sessionStore.listSessions();
      if (sessions.length) {
        activeSessionId = sessions[0].sessionId;
        await setKvConfig(KV_ACTIVE_SESSION_ID, activeSessionId);
        return applySessionToSnapshot(sessions[0], true);
      }
      return launchOrCreateStarterSession();
    },
    async close() {
      turnDriver.cancelActiveTurn();
      explicitlyClosed = true;
      const closedSnapshot: ChatSnapshot = {
        ...ctx.getChat(),
        chatProcessRunning: false,
        chatRuntimeClosing: false,
        status: "idle",
        activePlayback: null,
      };
      ctx.setChat(closedSnapshot);
      emitStandaloneChat();
      return clone(ctx.getChat());
    },
    async getRuntimeStatus() {
      await ensureInitialized();
      const chat = ctx.getChat();
      return {
        chatProcessRunning: Boolean(chat.chatProcessRunning),
        chatRuntimeClosing: false,
        state: chat.chatProcessRunning ? "running" : "idle",
      };
    },
    async getSnapshot() {
      await ensureInitialized();
      if (!explicitlyClosed && (!ctx.getChat().chatProcessRunning || !activeSessionId)) {
        return this.resumeLast();
      }
      return clone(ctx.getChat());
    },
    subscribe(listener) {
      ctx.chatListeners.add(listener);
      return () => {
        ctx.chatListeners.delete(listener);
      };
    },
    subscribeEvents(listener) {
      ctx.chatEventListeners.add(listener);
      return () => {
        ctx.chatEventListeners.delete(listener);
      };
    },
    async getHistory() {
      await ensureInitialized();
      if (!activeSessionId) return [];
      return sessionStore
        .listTurns(activeSessionId)
        .filter((node) => node.role !== "options")
        .map<ChatHistoryEntry>((node) => ({
          id: node.turnId,
          role: node.role,
          text: node.speaker && node.role === "assistant" ? `【${node.speaker}】${node.plainText}` : node.plainText,
          createdAt: node.createdAtMs,
          revertUserIndex: node.revertUserIndex,
        }));
    },
    async getHistoryVoice() {
      return [];
    },
    async prepareReplay(): Promise<ChatReplaySnapshot> {
      await ensureInitialized();
      const sid = activeSessionId ?? "";
      const session = sid ? sessionStore.getSession(sid) : undefined;
      const turns = sid ? sessionStore.listTurns(sid) : [];
      const entries = turns
        .filter((node) => node.role !== "options")
        .map((node, index) => ({
          id: node.turnId,
          key: `replay-${node.seq}`,
          position: index,
          role: node.role,
          text: node.plainText,
          speaker: node.speaker || (node.role === "user" ? session?.payload.playerCharacter || "我" : ""),
          body: node.plainText,
          canGenerate: false,
          voiceUrls: [],
          voiceSource: "",
          voiceLabel: "",
          createdAt: node.createdAtMs,
          frame: node.stageSnapshot
            ? {
                backgroundPath: node.stageSnapshot.backgroundPath
                  ? resolveStandaloneFileUrl(node.stageSnapshot.backgroundPath)
                  : "",
                bgmPath: node.stageSnapshot.bgmPath ? resolveStandaloneFileUrl(node.stageSnapshot.bgmPath) : "",
                cgPath: node.stageSnapshot.cgPath ? resolveStandaloneFileUrl(node.stageSnapshot.cgPath) : "",
                sprites: (node.stageSnapshot.sprites ?? []).map((sp) => ({
                  ...sp,
                  path: resolveStandaloneFileUrl(sp.path),
                  mouthSync: sp.mouthSync ? resolveStandaloneFileUrl(sp.mouthSync) : undefined,
                  modelUrl: sp.modelUrl ? resolveStandaloneFileUrl(sp.modelUrl) : "",
                  ...(sp.transitions?.length
                    ? {
                        transitions: sp.transitions.map((tr) => ({
                          ...tr,
                          fromUrl: resolveStandaloneFileUrl(tr.fromUrl),
                          url: resolveStandaloneFileUrl(tr.url),
                        })),
                      }
                    : {}),
                })),
                stats: node.stageSnapshot.stats,
              }
            : null,
        }));
      return {
        id: `replay-${Date.now()}`,
        sessionId: sid,
        branchId: session?.activeBranchId ?? "main",
        branchLabel: "主线",
        historyCount: entries.length,
        entries,
      };
    },
    async getReplay() {
      const snapshot = await this.prepareReplay();
      return { snapshot, generate: false };
    },
    async startReplay() {
      // Handled smoothly inside stage client replay view
    },
    async generateReplayVoice() {
      return { voiceUrls: [], voiceSource: "", voiceLabel: "" };
    },
    async cancelReplay() {},
    async controlReplay() {},
    async getTheme() {
      return { raw: {}, themeColor: ctx.config.system_config.theme_color || "#18181b" };
    },
    listThemes: () => delay(ctx.listPreviewThemes()),
    getThemeManifest: (id) => delay(ctx.resolvePreviewManifest(id) ?? ctx.resolvePreviewManifest("default")!),
    async getActiveThemeId() {
      await ensureInitialized();
      return ctx.getActiveThemeId();
    },
    async setActiveThemeId(id) {
      ctx.setActiveThemeId(id);
      await setKvConfig(KV_ACTIVE_THEME_ID, id);
    },
    async uploadTheme() {
      throw new Error("Standalone 模式暂仅支持内置主题切换。");
    },
    async uploadAttachments(files) {
      const vfsPaths = await stageUploadedFiles(files, "attachments");
      return {
        attachments: files.map((file, idx) => ({
          kind: file.type.startsWith("image/") ? ("image" as const) : ("file" as const),
          name: file.name,
          path: vfsPaths[idx],
        })),
      };
    },
    saveTheme: baseChat.saveTheme,
    deleteTheme: baseChat.deleteTheme,
    async command(command: ChatCommand): Promise<ChatCommandResult> {
      await ensureInitialized();
      if (!activeSessionId) {
        await this.resumeLast();
      }
      const session = activeSessionId ? sessionStore.getSession(activeSessionId) : undefined;

      switch (command.type) {
        case "send-message":
        case "submit-option": {
          if (!session) break;
          const userText =
            command.type === "submit-option" && typeof command.payload === "object" && command.payload
              ? String((command.payload as { choiceId?: string }).choiceId ?? "")
              : extractCommandText(command.payload);
          if (!userText) break;
          void turnDriver.runTurn({
            session,
            userText,
            isOptionSubmit: command.type === "submit-option",
          });
          break;
        }
        case "audio-playback-signal": {
          const payload = (command.payload ?? {}) as { playbackId?: string; status?: string };
          turnDriver.handlePlaybackSignal(payload);
          break;
        }
        case "dialog-advance":
          turnDriver.handleDialogAdvance();
          break;
        case "skip-speech":
          turnDriver.handleSkipSpeech();
          break;
        case "chat-input-state":
          if (command.payload && typeof command.payload === "object") {
            const p = command.payload as { hasText?: boolean; text?: string };
            if (typeof p.text === "string") {
              latestUserInputDraft = p.text;
            }
          }
          break;
        case "dismiss-cg":
          ctx.setChat({ ...ctx.getChat(), cgPath: "" });
          emitStandaloneChat();
          emitStageEvent({ v: 1, seq: nextSeq(), ts: Date.now(), type: "cg.hide" });
          break;
        case "clear-history": {
          if (!session) break;
          turnDriver.cancelActiveTurn();
          await sessionStore.truncateAfter(session.sessionId, 0);
          await sessionStore.updateSessionMeta(session.sessionId, {
            prologueCompleted: false,
            prologueStepId: "intro_0",
          });
          const lead =
            ctx.config.characters.find((c) => session.characters.includes(c.name)) ?? ctx.config.characters[0];
          if (lead) {
            await turnDriver.seedInitialPrologue(session.sessionId, lead);
          }
          const nextSnap = applySessionToSnapshot(sessionStore.getSession(session.sessionId)!, true);
          emitStandaloneChat();
          emitStageEvent({
            v: 1,
            seq: nextSeq(),
            ts: Date.now(),
            type: "history.replace",
            entries: nextSnap.historyEntries ?? [],
          });
          break;
        }
        case "revert-history": {
          if (!session) break;
          const userIndex = Number((command.payload as { userIndex?: number } | undefined)?.userIndex ?? -1);
          if (userIndex >= 0) {
            turnDriver.cancelActiveTurn();
            const res = await sessionStore.truncateFromUserTurnIndex(session.sessionId, userIndex);
            const updatedSession = sessionStore.getSession(session.sessionId)!;
            const nextSnap = applySessionToSnapshot(updatedSession, true);
            nextSnap.inputDraft = res.revertedUserText || latestUserInputDraft;
            ctx.setChat(nextSnap);
            emitStandaloneChat();
            emitStageEvent({
              v: 1,
              seq: nextSeq(),
              ts: Date.now(),
              type: "history.replace",
              entries: nextSnap.historyEntries ?? [],
            });
            return clone(ctx.getChat());
          }
          break;
        }
        case "reroll": {
          if (!session) break;
          const turns = sessionStore.listTurns(session.sessionId);
          const lastUser = [...turns].reverse().find((t) => t.role === "user");
          if (lastUser) {
            turnDriver.cancelActiveTurn();
            await sessionStore.truncateAfter(session.sessionId, lastUser.seq - 1);
            const refreshed = sessionStore.getSession(session.sessionId)!;
            applySessionToSnapshot(refreshed, true);
            emitStandaloneChat();
            void turnDriver.runTurn({ session: refreshed, userText: lastUser.plainText });
          }
          break;
        }
        case "set-character-outfit": {
          if (!session || !command.payload || typeof command.payload !== "object") break;
          const p = command.payload as { characterName?: string; activeGroup?: string; locked?: boolean };
          if (!p.characterName || p.activeGroup === undefined) break;
          const nextOutfits = {
            ...session.outfits,
            [p.characterName]: {
              characterName: p.characterName,
              activeGroup: p.activeGroup,
              locked: Boolean(p.locked),
              updatedAtMs: Date.now(),
            },
          };
          await sessionStore.updateSessionMeta(session.sessionId, { outfits: nextOutfits });
          const nextChat = applySessionToSnapshot(sessionStore.getSession(session.sessionId)!, true);
          ctx.setChat(nextChat);
          emitStandaloneChat();
          break;
        }
        case "set-auto-outfit-switch": {
          if (!session) break;
          const enabled = Boolean((command.payload as { enabled?: boolean } | undefined)?.enabled);
          await sessionStore.updateSessionMeta(session.sessionId, { autoOutfitSwitch: enabled });
          ctx.setChat({ ...ctx.getChat(), autoOutfitSwitch: enabled });
          emitStandaloneChat();
          break;
        }
        case "open-history": {
          const entries = await this.getHistory();
          return { ...clone(ctx.getChat()), historyEntries: entries };
        }
        case "copy-history": {
          const entries = await this.getHistory();
          const clipboardText = entries.map((e) => e.text).join("\n");
          return { ...clone(ctx.getChat()), clipboardText };
        }
        default:
          break;
      }

      return clone(ctx.getChat());
    },
  };

  async function generateCharacterBrief(input: { name: string; setting: string }) {
    await ensureInitialized();
    const provider = ctx.config.api_config.llm_provider || "硅基流动";
    const key = (ctx.config.api_config.llm_api_key?.[provider] ?? "").trim();
    if (!key && provider !== "Ollama") {
      return baseCharacters.generateBrief(input);
    }
    const preset = getLlmProviderPreset(provider);
    const adapter = resolveLlmAdapter(provider);
    const res = await adapter.complete(
      {
        provider,
        apiKey: key,
        baseUrl: ctx.config.api_config.llm_base_urls?.[provider] || preset.defaultBaseUrl,
        model: ctx.config.api_config.llm_model?.[provider] || preset.defaultModel,
        messages: [
          { role: "system", content: "根据角色名称与设定，用2句话凝练一段中文人物简介。" },
          { role: "user", content: `角色：${input.name}\n设定：${input.setting}` },
        ],
        maxTokens: 256,
      },
      standaloneHttpRequest,
    );
    return { characterBrief: res.content.trim(), message: "生成成功" };
  }

  return {
    agent: createAgentPreviewPlatform(),
    avatarRuntimes: createAvatarRuntimesPreviewPlatform(),
    characterRelation: {
      async getRelationGraph(owner) {
        await ensureInitialized();
        return baseRelation.getRelationGraph(owner);
      },
      async applyRelationChanges(owner, operations) {
        await ensureInitialized();
        const updated = await baseRelation.applyRelationChanges(owner, operations);
        await persistAppConfig();
        return updated;
      },
    },
    modelAssets: createModelAssetsPreviewPlatform(ctx),
    musicCover: createMusicCoverPreviewPlatform(ctx),
    effects: {
      async list() {
        await ensureInitialized();
        return clone(ctx.config.effect_list);
      },
      async save(effect, originalName) {
        await ensureInitialized();
        const saved = await baseEffects.save(effect, originalName);
        await persistAppConfig();
        return saved;
      },
      async delete(name) {
        await ensureInitialized();
        await baseEffects.delete(name);
        await persistAppConfig();
      },
      async export(name) {
        await ensureInitialized();
        return baseEffects.export(name);
      },
      async import(items) {
        await ensureInitialized();
        const imported = await baseEffects.import(items);
        await persistAppConfig();
        return imported;
      },
      async uploadAudio(input) {
        await ensureInitialized();
        const existing = ctx.config.effect_list.find((e) => e.name === input.name)?.audio_list ?? [];
        const relocated = await relocatePathsList(
          input.paths,
          `vfs://effects/${sanitizeVfsFileName(input.name)}/audio`,
          existing,
        );
        const res = await baseEffects.uploadAudio({ ...input, paths: relocated });
        await persistAppConfig();
        return res;
      },
      async uploadImages(input) {
        await ensureInitialized();
        const existing = ctx.config.effect_list.find((e) => e.name === input.name)?.image_list ?? [];
        const relocated = await relocatePathsList(
          input.paths,
          `vfs://effects/${sanitizeVfsFileName(input.name)}/images`,
          existing,
        );
        const res = await baseEffects.uploadImages({ ...input, paths: relocated });
        await persistAppConfig();
        return res;
      },
      async uploadImageAudio(input) {
        await ensureInitialized();
        const existing = ctx.config.effect_list.find((e) => e.name === input.name)?.image_audio_list ?? [];
        const [relocatedPath] = await relocatePathsList(
          [input.path],
          `vfs://effects/${sanitizeVfsFileName(input.name)}/image-audio`,
          existing,
        );
        const res = await baseEffects.uploadImageAudio({ ...input, path: relocatedPath });
        await persistAppConfig();
        return res;
      },
      async uploadAmbient(input) {
        await ensureInitialized();
        const existing = ctx.config.effect_list.find((e) => e.name === input.name)?.ambient_list ?? [];
        const relocated = await relocatePathsList(
          input.paths,
          `vfs://effects/${sanitizeVfsFileName(input.name)}/ambient`,
          existing,
        );
        const res = await baseEffects.uploadAmbient({ ...input, paths: relocated });
        await persistAppConfig();
        return res;
      },
      async deleteAmbient(name, index) {
        await ensureInitialized();
        const res = await baseEffects.deleteAmbient(name, index);
        await persistAppConfig();
        return res;
      },
      async saveAmbientTags(input) {
        await ensureInitialized();
        const res = await baseEffects.saveAmbientTags(input);
        await persistAppConfig();
        return res;
      },
      async saveAmbientLayers(input) {
        await ensureInitialized();
        const res = await baseEffects.saveAmbientLayers(input);
        await persistAppConfig();
        return res;
      },
      async uploadAmbientAudio(input) {
        await ensureInitialized();
        const existing = ctx.config.effect_list.find((e) => e.name === input.name)?.ambient_audio_list ?? [];
        const [relocatedPath] = await relocatePathsList(
          [input.path],
          `vfs://effects/${sanitizeVfsFileName(input.name)}/ambient-audio`,
          existing,
        );
        const res = await baseEffects.uploadAmbientAudio({ ...input, path: relocatedPath });
        await persistAppConfig();
        return res;
      },
      async deleteAudio(name, index) {
        await ensureInitialized();
        const res = await baseEffects.deleteAudio(name, index);
        await persistAppConfig();
        return res;
      },
      async deleteAllAudio(name) {
        await ensureInitialized();
        const res = await baseEffects.deleteAllAudio(name);
        await persistAppConfig();
        return res;
      },
      async deleteImage(name, index) {
        await ensureInitialized();
        const res = await baseEffects.deleteImage(name, index);
        await persistAppConfig();
        return res;
      },
      async saveAudioTags(input) {
        await ensureInitialized();
        const res = await baseEffects.saveAudioTags(input);
        await persistAppConfig();
        return res;
      },
      async saveImageTags(input) {
        await ensureInitialized();
        const res = await baseEffects.saveImageTags(input);
        await persistAppConfig();
        return res;
      },
    },
    knowledge: createKnowledgePreviewPlatform(ctx),
    logs: createLogsPreviewPlatform(),
    mcp: createMcpPreviewPlatform(),
    perception: createPerceptionPreviewPlatform(ctx),
    plugins: createPluginsPreviewPlatform(),
    runtime: createRuntimePreviewPlatform(),
    story: createStoryPreviewPlatform(
      () => clone(ctx.getChat()),
      (snapshot) => ctx.setChat(snapshot),
      () => {},
    ),
    tasks: createTasksPreviewPlatform(),
    tools: createToolsPreviewPlatform(),
    files: {
      ...baseFiles,
      fileUrl: (path) => resolveStandaloneFileUrl(path),
      thumbnailUrl: (path) => resolveStandaloneFileUrl(path),
      async thumbnailBatch(paths) {
        return Object.fromEntries(paths.filter(Boolean).map((p) => [p, resolveStandaloneFileUrl(p)]));
      },
    },
    config: {
      ...baseConfig,
      async get() {
        await ensureInitialized();
        return clone(ctx.config);
      },
      async saveApi(apiConfig: ApiConfig) {
        await ensureInitialized();
        ctx.config.api_config = clone(apiConfig);
        await persistAppConfig();
        return clone(ctx.config.api_config);
      },
      async saveSystem(systemConfig: SystemConfig) {
        await ensureInitialized();
        ctx.config.system_config = clone(systemConfig);
        await persistAppConfig();
        return clone(ctx.config.system_config);
      },
      async fetchLlmModels(input) {
        const adapter = resolveLlmAdapter(input.provider);
        return adapter.fetchModels(input, standaloneHttpRequest);
      },
      async testLlmConnection(input) {
        const adapter = resolveLlmAdapter(input.provider);
        return adapter.testConnection(input, standaloneHttpRequest);
      },
    },
    characters: {
      ...baseCharacters,
      async list() {
        await ensureInitialized();
        return clone(ctx.config.characters);
      },
      async revision() {
        await ensureInitialized();
        return JSON.stringify(ctx.config.characters);
      },
      async save(character, originalName) {
        await ensureInitialized();
        let nextCharacter = character;
        if (character.refer_audio_path && isVfsPath(character.refer_audio_path)) {
          const prefix = sanitizeVfsFileName(character.sprite_prefix || character.name || "character");
          const [relocatedRefer] = await relocatePathsList(
            [character.refer_audio_path],
            `vfs://characters/${prefix}/models`,
          );
          nextCharacter = { ...character, refer_audio_path: relocatedRefer };
        }
        const saved = await baseCharacters.save(nextCharacter, originalName);
        await persistAppConfig();
        return saved;
      },
      async delete(name) {
        await ensureInitialized();
        await baseCharacters.delete(name);
        await persistAppConfig();
      },
      async uploadSprites(input) {
        await ensureInitialized();
        const targetChar = ctx.config.characters.find((c) => c.name === input.name);
        if (!targetChar) {
          throw new Error(`角色不存在：${input.name}`);
        }
        const prefix = sanitizeVfsFileName(targetChar.sprite_prefix || targetChar.name || "character");
        const existingPaths = targetChar.sprites.map((sp) => sp.path);
        const uploadedPaths = await relocatePathsList(input.paths, `vfs://characters/${prefix}/sprites`, existingPaths);
        const start = targetChar.sprites.length;
        const groupName = input.group?.trim();
        const targetGroup = !groupName || groupName === "默认" ? undefined : groupName;
        const nextSprites = uploadedPaths.map((path) => ({
          path,
          ...(targetGroup ? { group: targetGroup } : {}),
        }));
        targetChar.sprites = [...targetChar.sprites, ...nextSprites];
        if (targetGroup) {
          const currentGroups = targetChar.sprite_groups ?? ["默认"];
          if (!currentGroups.includes(targetGroup)) {
            targetChar.sprite_groups = [...currentGroups, targetGroup];
          }
        }
        const existingTags = tagContents(input.emotionTags || targetChar.emotion_tags, start);
        const extraTags = uploadedPaths.map(() => "");
        targetChar.emotion_tags = numberedTags("立绘", [...existingTags, ...extraTags]);
        await persistAppConfig();
        return clone(targetChar);
      },
      async uploadSpriteVoice(input) {
        await ensureInitialized();
        const targetChar = ctx.config.characters.find((c) => c.name === input.name);
        const prefix = sanitizeVfsFileName(targetChar?.sprite_prefix || input.name || "character");
        const existingVoices = (targetChar?.sprites ?? []).map((s) => s.voice_path ?? "").filter(Boolean);
        const [voicePath] = input.voicePath
          ? await relocatePathsList([input.voicePath], `vfs://characters/${prefix}/speech`, existingVoices)
          : [input.voicePath];
        const res = await baseCharacters.uploadSpriteVoice({ ...input, voicePath });
        await persistAppConfig();
        return res;
      },
      async autoGroupSprites(input) {
        await ensureInitialized();
        const res = await baseCharacters.autoGroupSprites(input);
        if (input.apply) {
          await persistAppConfig();
        }
        return res;
      },
      async autoLabelSprites(name) {
        await ensureInitialized();
        const res = await baseCharacters.autoLabelSprites(name);
        await persistAppConfig();
        return res;
      },
      async importGeneratedSprites(input) {
        await ensureInitialized();
        const res = await baseCharacters.importGeneratedSprites(input);
        await persistAppConfig();
        return res;
      },
      async deleteSprite(name, idx) {
        await ensureInitialized();
        const res = await baseCharacters.deleteSprite(name, idx);
        await persistAppConfig();
        return res;
      },
      async deleteAllSprites(name) {
        await ensureInitialized();
        const res = await baseCharacters.deleteAllSprites(name);
        await persistAppConfig();
        return res;
      },
      async deleteSpriteVoice(name, idx) {
        await ensureInitialized();
        const res = await baseCharacters.deleteSpriteVoice(name, idx);
        await persistAppConfig();
        return res;
      },
      async saveEmotionTags(name, emotionTags) {
        await ensureInitialized();
        const res = await baseCharacters.saveEmotionTags(name, emotionTags);
        await persistAppConfig();
        return res;
      },
      async saveSpriteScale(name, scale) {
        await ensureInitialized();
        const res = await baseCharacters.saveSpriteScale(name, scale);
        await persistAppConfig();
        return res;
      },
      async saveSpriteGroups(input) {
        await ensureInitialized();
        const res = await baseCharacters.saveSpriteGroups(input);
        await persistAppConfig();
        return res;
      },
      async saveSpriteVoiceText(name, idx, voiceText) {
        await ensureInitialized();
        const res = await baseCharacters.saveSpriteVoiceText(name, idx, voiceText);
        await persistAppConfig();
        return res;
      },
      async saveSpriteVoiceType(name, idx, voiceType) {
        await ensureInitialized();
        const res = await baseCharacters.saveSpriteVoiceType(name, idx, voiceType);
        await persistAppConfig();
        return res;
      },
      async import(items) {
        await ensureInitialized();
        const importedAll: Character[] = [];
        for (const item of items) {
          if (item instanceof Blob) {
            const parsed = await importCharPackage(item, [...ctx.config.characters, ...importedAll]);
            importedAll.push(...parsed);
          } else if (typeof item === "string" && isVfsPath(item)) {
            const blob = await getVfsBlobAsync(item);
            if (!blob) throw new Error(`未找到角色包文件: ${item}`);
            const parsed = await importCharPackage(blob, [...ctx.config.characters, ...importedAll]);
            importedAll.push(...parsed);
          } else {
            throw new Error("请通过文件选择器导入本地 .char 或 .zip 角色包。");
          }
        }
        ctx.config.characters.push(...importedAll);
        await persistAppConfig();
        return clone(importedAll);
      },
      async export(name) {
        await ensureInitialized();
        const targetChar = ctx.config.characters.find((c) => c.name === name);
        if (!targetChar) throw new Error(`角色不存在：${name}`);
        const { filename, blob } = await exportCharPackage(targetChar, { triggerDownload: true });
        const exportVfsPath = `vfs://exports/${filename}`;
        await putVfsBlob(exportVfsPath, blob, { mimeType: "application/zip", persist: false });
        return exportVfsPath;
      },
      async ensureBriefs(names) {
        await ensureInitialized();
        const selected: (typeof ctx.config.characters)[number][] = [];
        const generatedNames: string[] = [];
        const seen = new Set<string>();
        let changed = false;
        for (const rawName of names) {
          const key = characterNameKey(String(rawName ?? ""));
          if (!key || seen.has(key)) continue;
          seen.add(key);
          const char = ctx.config.characters.find((c) => characterNameKey(c.name) === key);
          if (!char) continue;
          if (!char.character_brief?.trim()) {
            const briefResult = await generateCharacterBrief({
              name: char.name,
              setting: char.character_setting,
            });
            if (briefResult.characterBrief?.trim()) {
              char.character_brief = briefResult.characterBrief.trim();
              generatedNames.push(char.name);
              changed = true;
            }
          }
          selected.push(char);
        }
        if (changed) {
          await persistAppConfig();
        }
        return {
          characters: clone(selected),
          generatedNames,
        };
      },
      async generateBrief(input) {
        return generateCharacterBrief(input);
      },
      async generateSetting(input) {
        await ensureInitialized();
        const provider = ctx.config.api_config.llm_provider || "硅基流动";
        const key = (ctx.config.api_config.llm_api_key?.[provider] ?? "").trim();
        if (!key && provider !== "Ollama") {
          return baseCharacters.generateSetting(input);
        }
        const preset = getLlmProviderPreset(provider);
        const adapter = resolveLlmAdapter(provider);
        const res = await adapter.complete(
          {
            provider,
            apiKey: key,
            baseUrl: ctx.config.api_config.llm_base_urls?.[provider] || preset.defaultBaseUrl,
            model: ctx.config.api_config.llm_model?.[provider] || preset.defaultModel,
            messages: [
              { role: "system", content: "扩写角色背景设定与说话语气特点，结构清晰，使用中文。" },
              { role: "user", content: `角色名：${input.name}\n灵感关键词：${input.setting}` },
            ],
            maxTokens: 700,
          },
          standaloneHttpRequest,
        );
        return {
          characterSetting: res.content.trim(),
          characterBrief: `${input.name || "角色"}的个性化设定。`,
          message: "生成成功",
        };
      },
    },
    backgrounds: {
      ...baseBackgrounds,
      async list() {
        await ensureInitialized();
        return clone(ctx.config.background_list);
      },
      async save(bg, origName) {
        await ensureInitialized();
        const res = await baseBackgrounds.save(bg, origName);
        await persistAppConfig();
        return res;
      },
      async delete(name) {
        await ensureInitialized();
        await baseBackgrounds.delete(name);
        await persistAppConfig();
      },
      async import(items) {
        await ensureInitialized();
        const imported = await baseBackgrounds.import(items);
        await persistAppConfig();
        return imported;
      },
      async autoLabelImages(name) {
        await ensureInitialized();
        const res = await baseBackgrounds.autoLabelImages(name);
        await persistAppConfig();
        return res;
      },
      async uploadImages(input) {
        await ensureInitialized();
        const bg = ctx.config.background_list.find((b) => b.name === input.name);
        const prefix = sanitizeVfsFileName(bg?.sprite_prefix || input.name || "background");
        const existing = (bg?.sprites ?? []).map((s) => s.path);
        const relocated = await relocatePathsList(input.paths, `vfs://backgrounds/${prefix}/images`, existing);
        const res = await baseBackgrounds.uploadImages({ ...input, paths: relocated });
        await persistAppConfig();
        return res;
      },
      async uploadBgm(input) {
        await ensureInitialized();
        const bg = ctx.config.background_list.find((b) => b.name === input.name);
        const prefix = sanitizeVfsFileName(bg?.sprite_prefix || input.name || "background");
        const existing = bg?.bgm_list ?? [];
        const relocated = await relocatePathsList(input.paths, `vfs://backgrounds/${prefix}/bgm`, existing);
        const res = await baseBackgrounds.uploadBgm({ ...input, paths: relocated });
        await persistAppConfig();
        return res;
      },
      async deleteImage(name, idx) {
        await ensureInitialized();
        const res = await baseBackgrounds.deleteImage(name, idx);
        await persistAppConfig();
        return res;
      },
      async deleteAllImages(name) {
        await ensureInitialized();
        const res = await baseBackgrounds.deleteAllImages(name);
        await persistAppConfig();
        return res;
      },
      async deleteBgm(name, idx) {
        await ensureInitialized();
        const res = await baseBackgrounds.deleteBgm(name, idx);
        await persistAppConfig();
        return res;
      },
      async deleteAllBgm(name) {
        await ensureInitialized();
        const res = await baseBackgrounds.deleteAllBgm(name);
        await persistAppConfig();
        return res;
      },
      async saveImageTags(input) {
        await ensureInitialized();
        const res = await baseBackgrounds.saveImageTags(input);
        await persistAppConfig();
        return res;
      },
      async saveBgmTags(input) {
        await ensureInitialized();
        const res = await baseBackgrounds.saveBgmTags(input);
        await persistAppConfig();
        return res;
      },
    },
    templates: {
      ...baseTemplates,
      async generate(input) {
        await ensureInitialized();
        const nextVoice = input.voiceLanguage?.trim();
        if (nextVoice && nextVoice !== ctx.config.system_config.voice_language) {
          ctx.config.system_config.voice_language = nextVoice;
          await persistAppConfig();
        }
        return generateStandaloneTemplateSummary(input, ctx.config);
      },
      async list() {
        await ensureInitialized();
        return clone(ctx.getTemplates());
      },
      async save(template) {
        await ensureInitialized();
        const res = await baseTemplates.save(template);
        await persistTemplates();
        return res;
      },
      async getPresets() {
        await ensureInitialized();
        return baseTemplates.getPresets();
      },
      async savePresets(library) {
        await ensureInitialized();
        const res = await baseTemplates.savePresets(library);
        await persistUserPromptPresets();
        return res;
      },
      async getSession() {
        await ensureInitialized();
        return baseTemplates.getSession();
      },
      async saveSession(session) {
        await ensureInitialized();
        const res = await baseTemplates.saveSession(session);
        await persistTemplateSession();
        return res;
      },
    },
    chat: chatPlatform,
  };
}
