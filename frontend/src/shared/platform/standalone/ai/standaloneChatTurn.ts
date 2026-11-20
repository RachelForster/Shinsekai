import type { Character } from "../../slices/characterTypes";
import type {
  CharacterOutfitState,
  ChatOption,
  ChatSnapshot,
  ChatSprite,
  ChatStageEvent,
  ChatStat,
} from "../../slices/chatTypes";
import type { ApiConfig } from "../../slices/configTypes";
import { advancePrologueStep, createInitialPrologueState } from "../packages/presetLoader";
import type { StandaloneSessionRecord, StandaloneSessionStore } from "../storage/sessionStore";
import { getVfsBlobAsync, resolveVfsUrl } from "../storage/vfsBlobRegistry";
import { autoCompactIfNeeded, getCompactionLimits, trimMessagesToBudget } from "./compactManager";
import { resolveLlmAdapter, resolveTtsAdapter } from "./adapters/registry";
import { getLlmProviderPreset } from "./adapters/llm/presets";
import { parseStandaloneDialogOutput } from "./dialogOutputParser";
import { buildStandaloneDialogSystemPrompt } from "./dialogPromptBuilder";
import type { StandaloneHttpClient } from "./httpClient";

export interface ChatTurnDriverContext {
  getApiConfig: () => ApiConfig;
  getCharacters: () => Character[];
  getChat: () => ChatSnapshot;
  setChat: (next: ChatSnapshot) => void;
  emitChat: () => void;
  emitStageEvent: (event: ChatStageEvent) => void;
  sessionStore: StandaloneSessionStore;
  httpClient: StandaloneHttpClient;
  resolveFileUrl: (path: string) => string;
  onProgressCheckpoint?: () => void;
}

export class StandaloneChatTurnDriver {
  private activeAbort: AbortController | null = null;
  private activePlaybackId: string | null = null;
  private pendingAdvanceResolvers: Array<(reason: "advance" | "playback" | "skip") => void> = [];
  private activeBlobAudioUrls: string[] = [];
  private playbackSeq = 0;

  constructor(private readonly ctx: ChatTurnDriverContext) {}

  private resolveAllPendingAdvances(reason: "advance" | "playback" | "skip") {
    const callbacks = this.pendingAdvanceResolvers.splice(0);
    for (const cb of callbacks) {
      cb(reason);
    }
  }

  private waitForPlaybackOrAdvance(
    playbackId: string | null,
    timeoutMs: number,
    signal: AbortSignal,
  ): Promise<"advance" | "playback" | "skip" | "timeout"> {
    if (signal.aborted) {
      return Promise.resolve("skip");
    }
    this.activePlaybackId = playbackId;
    return new Promise((resolve) => {
      let settled = false;
      const done = (reason: "advance" | "playback" | "skip" | "timeout") => {
        if (settled) return;
        settled = true;
        if (this.activePlaybackId === playbackId) {
          this.activePlaybackId = null;
        }
        globalThis.clearTimeout(timer);
        signal.removeEventListener("abort", onAbort);
        resolve(reason);
      };

      const timer = globalThis.setTimeout(() => done("timeout"), timeoutMs);
      const onAbort = () => done("skip");
      signal.addEventListener("abort", onAbort, { once: true });

      this.pendingAdvanceResolvers.push((reason) => done(reason));
    });
  }

  handlePlaybackSignal(payload: { playbackId?: string; status?: string }) {
    if (!this.activePlaybackId) return;
    if (payload.playbackId && payload.playbackId !== this.activePlaybackId) return;
    if (payload.status === "finished" || payload.status === "failed" || payload.status === "interrupted") {
      this.resolveAllPendingAdvances("playback");
    }
  }

  handleDialogAdvance() {
    if (this.pendingAdvanceResolvers.length > 0) {
      if (this.activePlaybackId) {
        this.ctx.emitStageEvent({
          v: 1,
          seq: Date.now(),
          ts: Date.now(),
          type: "tts.skip",
          playbackId: this.activePlaybackId,
        });
      }
      this.resolveAllPendingAdvances("advance");
    }
  }

  handleSkipSpeech() {
    this.ctx.emitStageEvent({
      v: 1,
      seq: Date.now(),
      ts: Date.now(),
      type: "tts.skip",
      playbackId: this.activePlaybackId ?? undefined,
    });
    this.resolveAllPendingAdvances("skip");
  }

  cancelActiveTurn() {
    this.activeAbort?.abort();
    this.activeAbort = null;
    this.resolveAllPendingAdvances("skip");
    for (const url of this.activeBlobAudioUrls.splice(0)) {
      if (url.startsWith("blob:") && typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // Ignore revoke failures
        }
      }
    }
  }

  private resolveCharacterSprite(
    character: Character,
    requestedSprite: number | string | undefined,
    outfits: Record<string, CharacterOutfitState>,
  ): {
    url: string;
    mouthSync?: string;
    portraitCrop?: ChatSprite["portraitCrop"];
    transitions?: ChatSprite["transitions"];
  } {
    const sprites = character.sprites ?? [];
    if (!sprites.length) {
      return { url: "" };
    }

    const activeGroup = outfits[character.name]?.activeGroup || character.default_sprite_group || "";
    const groupMatches = activeGroup
      ? sprites.filter((item) => item.group === activeGroup)
      : sprites;
    const pool = groupMatches.length ? groupMatches : sprites;

    let selected = pool[0];
    if (typeof requestedSprite === "number" && Number.isFinite(requestedSprite)) {
      const idx = Math.max(0, Math.min(sprites.length - 1, Math.round(requestedSprite) - 1));
      const direct = sprites[idx];
      if (!activeGroup || direct.group === activeGroup || character.fallback_to_default_group !== false) {
        selected = direct;
      }
    } else if (typeof requestedSprite === "string" && requestedSprite.trim()) {
      const query = requestedSprite.trim().toLowerCase();
      const tagLines = (character.emotion_tags || "").split(/\r?\n/);
      const matchedIdx = tagLines.findIndex((line) => line.toLowerCase().includes(query));
      if (matchedIdx >= 0 && sprites[matchedIdx]) {
        selected = sprites[matchedIdx];
      }
    }

    const resolvedUrl = this.ctx.resolveFileUrl(selected.path);
    const resolvedMouth = selected.mouth_sync ? this.ctx.resolveFileUrl(selected.mouth_sync) : undefined;
    const resolvedTransitions = character.sprite_transitions
      ?.filter((tr) => tr.to_path === selected.path || resolveVfsUrl(tr.to_path) === resolvedUrl)
      .map((tr) => ({
        fromUrl: this.ctx.resolveFileUrl(tr.from_path),
        url: this.ctx.resolveFileUrl(tr.path),
      }));

    return {
      url: resolvedUrl,
      mouthSync: resolvedMouth,
      portraitCrop: selected.portrait_crop ?? character.portrait_crop,
      transitions: resolvedTransitions?.length ? resolvedTransitions : undefined,
    };
  }

  private updateStageSprite(
    character: Character,
    requestedSprite: number | string | undefined,
    outfits: Record<string, CharacterOutfitState>,
  ) {
    const current = this.ctx.getChat();
    const resolved = this.resolveCharacterSprite(character, requestedSprite, outfits);
    const url = resolved.url;
    if (!url) return;

    const existingIdx = current.sprites.findIndex(
      (s) => s.label === character.name || s.identityKey === character.name,
    );
    const nextSprite: ChatSprite = {
      id: existingIdx >= 0 ? current.sprites[existingIdx].id : `sprite-${character.name}`,
      identityKey: character.name,
      label: character.name,
      path: url,
      scale: character.sprite_scale || 1,
      avatarType: character.avatar_type || "static",
      modelUrl: "",
      mouthSync: resolved.mouthSync,
      portraitCrop: resolved.portraitCrop,
      transitions: resolved.transitions,
    };

    const nextSprites = [...current.sprites];
    if (existingIdx >= 0) {
      nextSprites[existingIdx] = { ...nextSprites[existingIdx], ...nextSprite };
    } else {
      nextSprites.push(nextSprite);
    }

    this.ctx.setChat({
      ...current,
      characterName: character.name,
      sprites: nextSprites,
    });
    this.ctx.emitChat();
    this.ctx.emitStageEvent({
      v: 1,
      seq: Date.now(),
      ts: Date.now(),
      type: "sprite.show",
      characterName: character.name,
      identityKey: character.name,
      url,
      scale: nextSprite.scale ?? 1,
      avatarType: nextSprite.avatarType,
      modelUrl: "",
      mouthSync: nextSprite.mouthSync,
      portraitCrop: nextSprite.portraitCrop,
      transitions: nextSprite.transitions,
    });
  }

  private async synthesizeTtsUrl(
    character: Character | undefined,
    speech: string,
    apiConfig: ApiConfig,
    signal: AbortSignal,
  ): Promise<string | null> {
    const ttsProvider = (apiConfig.tts_provider || "none").trim();
    const adapter = resolveTtsAdapter(ttsProvider);
    if (!adapter || !speech.trim()) {
      return null;
    }

    let referAudioBlob: Blob | undefined;
    if (character?.refer_audio_path) {
      referAudioBlob = await getVfsBlobAsync(character.refer_audio_path);
    }

    try {
      const blob = await adapter.synthesize(
        {
          text: speech,
          characterName: character?.name ?? "角色",
          speed: character?.speech_speed ?? apiConfig.tts_speed ?? 1.0,
          volume: character?.speech_volume ?? 1.0,
          referAudioBlob,
          referAudioText: character?.prompt_text,
          referAudioLang: character?.prompt_lang,
          apiConfig,
          signal,
        },
        (apiConfig.tts_extra_configs?.[ttsProvider] ?? {}) as Record<string, unknown>,
        this.ctx.httpClient,
      );

      if (!blob) return null;
      if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(blob);
        this.activeBlobAudioUrls.push(url);
        return url;
      }
      return null;
    } catch {
      // Never abort text conversation just because cloud TTS returned an error
      return null;
    }
  }

  async runTurn(input: {
    session: StandaloneSessionRecord;
    userText: string;
    isOptionSubmit?: boolean;
  }): Promise<void> {
    this.cancelActiveTurn();
    const abort = new AbortController();
    this.activeAbort = abort;

    const { session, userText, isOptionSubmit } = input;
    const apiConfig = this.ctx.getApiConfig();
    const characters = this.ctx.getCharacters();
    const activeCharacters = session.characters.length
      ? characters.filter((c) => session.characters.includes(c.name))
      : characters.slice(0, 1);
    const primaryChar = activeCharacters[0] ?? characters[0];
    const fallbackName = primaryChar?.name ?? "星奈";

    if (isOptionSubmit) {
      const currentOptions = this.ctx.getChat().options ?? [];
      const pickedIdx = currentOptions.findIndex(
        (opt) => (typeof opt === "string" ? opt : opt.label) === userText,
      );
      if (pickedIdx >= 0) {
        await this.ctx.sessionStore.markOptionSelected(session.sessionId, pickedIdx);
      }
    }

    const currentSnapshot = this.ctx.getChat();
    this.ctx.setChat({
      ...currentSnapshot,
      options: [],
      status: "generating",
      busyText: "思考回复中...",
    });
    this.ctx.emitChat();
    this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "options.clear" });
    this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "status.change", status: "generating" });

    // Record player's turn into non-destructive timeline
    await this.ctx.sessionStore.appendTurn(session.sessionId, {
      role: "user",
      speaker: session.payload.playerCharacter || "我",
      plainText: userText,
      renderedHtml: userText,
      outfitSnapshot: session.outfits,
      stageSnapshot: {
        backgroundPath: currentSnapshot.backgroundPath ?? "",
        bgmPath: currentSnapshot.bgmPath ?? "",
        cgPath: currentSnapshot.cgPath ?? "",
        sprites: currentSnapshot.sprites,
        stats: currentSnapshot.stats ?? [],
      },
    });

    const provider = apiConfig.llm_provider || "硅基流动";
    const apiKey = (apiConfig.llm_api_key?.[provider] ?? "").trim();

    if (!apiKey && provider !== "Ollama") {
      await this.runPrologueOrKeyPromptTurn(session, userText, fallbackName, primaryChar, abort.signal);
      return;
    }

    const preset = getLlmProviderPreset(provider);
    const baseUrl = (apiConfig.llm_base_urls?.[provider] || apiConfig.llm_base_url || preset.defaultBaseUrl).trim();
    const model = (apiConfig.llm_model?.[provider] || preset.defaultModel).trim();
    const llmAdapter = resolveLlmAdapter(provider);

    try {
      const systemPrompt = buildStandaloneDialogSystemPrompt({
        characters: activeCharacters.length ? activeCharacters : characters.slice(0, 1),
        payload: session.payload,
        outfits: session.outfits,
        stats: this.ctx.getChat().stats,
        userDisplayName: this.ctx.getChat().userDisplayName,
      });

      const activeView = this.ctx.sessionStore.buildActiveLlmMessages(
        session.sessionId,
        systemPrompt,
      );
      const { maxContextTokens } = getCompactionLimits(apiConfig);
      const boundedMessages = trimMessagesToBudget(activeView.messages, maxContextTokens);

      const llmResult = await llmAdapter.complete(
        {
          provider,
          apiKey,
          baseUrl,
          model,
          messages: boundedMessages,
          temperature: apiConfig.temperature,
          presencePenalty: apiConfig.presence_penalty,
          frequencyPenalty: apiConfig.frequency_penalty,
          repetitionPenalty: apiConfig.repetition_penalty,
          signal: abort.signal,
        },
        this.ctx.httpClient,
      );

      if (abort.signal.aborted) return;

      const parsedItems = parseStandaloneDialogOutput(llmResult.content, fallbackName);
      const latestSession = this.ctx.sessionStore.getSession(session.sessionId) ?? session;
      const outfits = structuredClone(latestSession.outfits ?? {});
      let nextStats: ChatStat[] = [...(this.ctx.getChat().stats ?? [])];
      let nextOptions: ChatOption[] = [];

      for (const item of parsedItems) {
        if (item.kind === "stat") {
          nextStats = item.stats;
          this.ctx.setChat({ ...this.ctx.getChat(), stats: nextStats });
          this.ctx.emitChat();
          this.ctx.emitStageEvent({
            v: 1,
            seq: Date.now(),
            ts: Date.now(),
            type: "stats.update",
            stats: nextStats,
          });
        } else if (item.kind === "choice") {
          nextOptions = item.options;
        }
      }

      const speechItems = parsedItems.filter(
        (item): item is Extract<typeof item, { kind: "speech" }> => item.kind === "speech",
      );

      for (let i = 0; i < speechItems.length; i += 1) {
        if (abort.signal.aborted) return;
        const seg = speechItems[i];
        const targetChar =
          characters.find((c) => c.name === seg.characterName) ?? (seg.isNarration ? undefined : primaryChar);

        if (targetChar && seg.outfit && latestSession.autoOutfitSwitch && !outfits[targetChar.name]?.locked) {
          if (targetChar.sprite_groups?.includes(seg.outfit)) {
            outfits[targetChar.name] = {
              characterName: targetChar.name,
              activeGroup: seg.outfit,
              locked: false,
              updatedAtMs: Date.now(),
            };
          }
        }

        if (targetChar && !seg.isNarration) {
          this.updateStageSprite(targetChar, seg.sprite, outfits);
        }

        const displayText = seg.translate ? `${seg.speech}\n${seg.translate}` : seg.speech;
        const ttsUrl = seg.isNarration
          ? null
          : await this.synthesizeTtsUrl(targetChar, seg.speech, apiConfig, abort.signal);

        if (abort.signal.aborted) return;

        const speakerDisplay = seg.isNarration ? "" : seg.characterName;
        const snapshotBeforeLine = this.ctx.getChat();
        this.playbackSeq += 1;
        const playbackId = ttsUrl ? `standalone-pb-${this.playbackSeq}` : null;

        this.ctx.setChat({
          ...snapshotBeforeLine,
          characterName: speakerDisplay,
          dialogText: displayText,
          dialogHtml: "",
          busyText: "",
          status: playbackId ? "speaking" : "idle",
          activePlayback:
            playbackId && ttsUrl
              ? {
                  characterName: speakerDisplay || fallbackName,
                  playbackId,
                  seq: this.playbackSeq,
                  url: ttsUrl,
                  volume: targetChar?.speech_volume ?? 1.0,
                }
              : null,
        });
        this.ctx.emitChat();
        this.ctx.emitStageEvent({
          v: 1,
          seq: Date.now(),
          ts: Date.now(),
          type: "dialog.end",
          speaker: speakerDisplay,
          color: targetChar?.color ?? "#e2e8f0",
          isSystem: seg.isNarration,
          fullHtml: displayText,
          animate: true,
        });

        await this.ctx.sessionStore.appendTurn(session.sessionId, {
          role: seg.isNarration ? "system" : "assistant",
          speaker: speakerDisplay,
          plainText: displayText,
          renderedHtml: displayText,
          outfitSnapshot: outfits,
          stageSnapshot: {
            backgroundPath: this.ctx.getChat().backgroundPath ?? "",
            bgmPath: this.ctx.getChat().bgmPath ?? "",
            cgPath: this.ctx.getChat().cgPath ?? "",
            sprites: this.ctx.getChat().sprites,
            stats: nextStats,
          },
        });

        if (playbackId && ttsUrl) {
          this.ctx.emitStageEvent({
            v: 1,
            seq: Date.now(),
            ts: Date.now(),
            type: "tts.play",
            url: ttsUrl,
            characterName: speakerDisplay || fallbackName,
            playbackId,
            volume: targetChar?.speech_volume ?? 1.0,
          });
          await this.waitForPlaybackOrAdvance(playbackId, 30_000, abort.signal);
        } else if (i < speechItems.length - 1) {
          const paceMs = Math.min(4200, Math.max(1600, displayText.length * 85));
          await this.waitForPlaybackOrAdvance(null, paceMs, abort.signal);
        }
      }

      if (abort.signal.aborted) return;

      if (nextOptions.length) {
        await this.ctx.sessionStore.appendTurn(session.sessionId, {
          role: "options",
          plainText: nextOptions.map((o) => (typeof o === "string" ? o : o.label)).join(" / "),
          options: nextOptions.map((o) => (typeof o === "string" ? o : o.label)),
        });
      }

      this.ctx.setChat({
        ...this.ctx.getChat(),
        status: "idle",
        busyText: "",
        activePlayback: null,
        options: nextOptions,
      });
      this.ctx.emitChat();
      if (nextOptions.length) {
        this.ctx.emitStageEvent({
          v: 1,
          seq: Date.now(),
          ts: Date.now(),
          type: "options.show",
          options: nextOptions,
        });
      }
      this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "reply.finished" });
      this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "status.change", status: "idle" });

      this.ctx.onProgressCheckpoint?.();

      void autoCompactIfNeeded({
        sessionId: session.sessionId,
        systemPrompt,
        sessionStore: this.ctx.sessionStore,
        apiConfig,
        llmAdapter,
        httpClient: this.ctx.httpClient,
        apiKey,
        baseUrl,
        model,
        lastUsageTokens: llmResult.usageTokens,
      });
    } catch (error) {
      if (abort.signal.aborted) return;
      const errMsg = error instanceof Error ? error.message : String(error);
      this.ctx.setChat({
        ...this.ctx.getChat(),
        status: "error",
        busyText: "",
        activePlayback: null,
        statusMessage: errMsg,
        notificationText: `对话请求失败：${errMsg}`,
      });
      this.ctx.emitChat();
      this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "status.change", status: "error" });
    }
  }

  private async runPrologueOrKeyPromptTurn(
    session: StandaloneSessionRecord,
    userText: string,
    fallbackName: string,
    primaryChar: Character | undefined,
    signal: AbortSignal,
  ) {
    const currentStepId = session.prologueStepId || "intro_0";
    const step = advancePrologueStep(currentStepId, userText, fallbackName);

    await this.ctx.sessionStore.updateSessionMeta(session.sessionId, {
      prologueStepId: step.nextStepId,
      prologueCompleted: step.completed,
      stats: step.stats,
    });

    this.ctx.setChat({
      ...this.ctx.getChat(),
      stats: step.stats,
    });
    this.ctx.emitChat();
    this.ctx.emitStageEvent({
      v: 1,
      seq: Date.now(),
      ts: Date.now(),
      type: "stats.update",
      stats: step.stats,
    });

    for (let i = 0; i < step.segments.length; i += 1) {
      if (signal.aborted) return;
      const seg = step.segments[i];
      if (primaryChar && !seg.narration) {
        this.updateStageSprite(primaryChar, seg.spriteIndex + 1, session.outfits);
      }
      const speakerDisplay = seg.narration ? "" : seg.speaker;
      this.ctx.setChat({
        ...this.ctx.getChat(),
        characterName: speakerDisplay,
        dialogText: seg.speech,
        dialogHtml: "",
        busyText: "",
        status: "idle",
      });
      this.ctx.emitChat();
      this.ctx.emitStageEvent({
        v: 1,
        seq: Date.now(),
        ts: Date.now(),
        type: "dialog.end",
        speaker: speakerDisplay,
        color: primaryChar?.color ?? "#7dd3fc",
        isSystem: Boolean(seg.narration),
        fullHtml: seg.speech,
        animate: true,
      });

      await this.ctx.sessionStore.appendTurn(session.sessionId, {
        role: seg.narration ? "system" : "assistant",
        speaker: speakerDisplay,
        plainText: seg.speech,
        renderedHtml: seg.speech,
        outfitSnapshot: session.outfits,
        stageSnapshot: {
          backgroundPath: this.ctx.getChat().backgroundPath ?? "",
          bgmPath: this.ctx.getChat().bgmPath ?? "",
          cgPath: this.ctx.getChat().cgPath ?? "",
          sprites: this.ctx.getChat().sprites,
          stats: step.stats,
        },
      });

      if (i < step.segments.length - 1) {
        const paceMs = Math.min(3500, Math.max(1400, seg.speech.length * 75));
        await this.waitForPlaybackOrAdvance(null, paceMs, signal);
      }
    }

    if (signal.aborted) return;

    await this.ctx.sessionStore.appendTurn(session.sessionId, {
      role: "options",
      plainText: step.options.join(" / "),
      options: step.options,
    });

    this.ctx.setChat({
      ...this.ctx.getChat(),
      status: "idle",
      busyText: "",
      options: step.options,
    });
    this.ctx.emitChat();
    this.ctx.emitStageEvent({
      v: 1,
      seq: Date.now(),
      ts: Date.now(),
      type: "options.show",
      options: step.options,
    });
    this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "reply.finished" });
    this.ctx.emitStageEvent({ v: 1, seq: Date.now(), ts: Date.now(), type: "status.change", status: "idle" });
    this.ctx.onProgressCheckpoint?.();
  }

  async seedInitialPrologue(sessionId: string, character: Character): Promise<void> {
    const existingTurns = this.ctx.sessionStore.listTurns(sessionId);
    if (existingTurns.length > 0) return;

    const initial = createInitialPrologueState(character.name);
    await this.ctx.sessionStore.updateSessionMeta(sessionId, {
      prologueStepId: initial.stepId,
      prologueCompleted: false,
      stats: initial.stats,
    });

    for (const seg of initial.segments) {
      await this.ctx.sessionStore.appendTurn(sessionId, {
        role: seg.narration ? "system" : "assistant",
        speaker: seg.narration ? "" : seg.speaker,
        plainText: seg.speech,
        renderedHtml: seg.speech,
        stageSnapshot: {
          backgroundPath: this.ctx.getChat().backgroundPath ?? "",
          bgmPath: "",
          cgPath: "",
          sprites: this.ctx.getChat().sprites,
          stats: initial.stats,
        },
      });
    }

    await this.ctx.sessionStore.appendTurn(sessionId, {
      role: "options",
      plainText: initial.options.join(" / "),
      options: initial.options,
    });

    const lastSeg = initial.segments[initial.segments.length - 1];
    this.ctx.setChat({
      ...this.ctx.getChat(),
      characterName: lastSeg.speaker,
      dialogText: lastSeg.speech,
      dialogHtml: "",
      options: initial.options,
      stats: initial.stats,
      status: "idle",
    });
    this.ctx.emitChat();
  }
}
