import type { ChatSnapshot } from "../../../shared/platform/types";
import { emptyChatState } from "./initialState";
import { withResolvedLayers } from "./layers";
import { chatStageSpriteCharacterName, normalizeChatStageSprites } from "./sprites";
import type { ChatAudioCommand, ChatStageBackgroundTransition, ChatStageSpriteMotion, ChatStageState } from "./types";

export function snapshotEventSeq(snapshot: ChatSnapshot) {
  return typeof snapshot.eventSeq === "number" && Number.isFinite(snapshot.eventSeq) ? snapshot.eventSeq : 0;
}

function transportFromSnapshot(snapshot: ChatSnapshot): Pick<ChatStageState, "transportMode" | "transportState"> {
  if (snapshot.wsUrl && snapshot.sessionId) {
    return {
      transportMode: "websocket",
      transportState: "connecting",
    };
  }
  return {
    transportMode: "snapshot",
    transportState: "connected",
  };
}

function shouldPreserveTransportState(state: ChatStageState) {
  return state.transportMode !== emptyChatState.transportMode || state.transportState !== emptyChatState.transportState;
}

function recoveryAudioCommands(state: ChatStageState, snapshot: ChatSnapshot, snapshotSeq: number): ChatAudioCommand[] {
  const commands: ChatAudioCommand[] = [];
  const previousPlayback = state.activePlayback;
  const activePlayback = snapshot.activePlayback;
  if (previousPlayback?.playbackId && (!activePlayback || previousPlayback.playbackId !== activePlayback.playbackId)) {
    commands.push({
      kind: "voice-stop",
      playbackId: previousPlayback.playbackId,
      seq: snapshotSeq,
    });
  }
  if (activePlayback?.playbackId && activePlayback.url) {
    commands.push({
      kind: "voice-play",
      characterName: activePlayback.characterName,
      playbackId: activePlayback.playbackId,
      rendererId: activePlayback.rendererId,
      seq: activePlayback.seq,
      url: activePlayback.url,
      volume: activePlayback.volume,
    });
  }

  const nextLoopKeys = new Set((snapshot.loopingEffects ?? []).map((effect) => effect.key));
  for (const effect of state.loopingEffects ?? []) {
    if (!nextLoopKeys.has(effect.key)) {
      commands.push({ key: effect.key, kind: "effect-loop-stop", seq: snapshotSeq });
    }
  }
  for (const effect of snapshot.loopingEffects ?? []) {
    commands.push({
      key: effect.key,
      kind: "effect-loop-start",
      seq: effect.seq,
      url: effect.url,
    });
  }
  return commands;
}

function restoreEffectImage(state: ChatStageState, snapshot: ChatSnapshot, receivedAt: number) {
  const image = snapshot.effectImage;
  if (!image || !Number.isFinite(snapshot.serverTimeMs)) return null;
  const remaining = Math.min(image.durationMs, Math.max(0, image.expiresAt - snapshot.serverTimeMs!));
  if (!Number.isFinite(remaining) || remaining <= 0) return null;
  let deadline = receivedAt + remaining;
  const previous = state.effectImage;
  if (state.sessionId === snapshot.sessionId && previous?.seq === image.seq && previous.url === image.url) {
    // Repeated snapshots cannot restart or extend an already displayed image.
    deadline = Math.min(deadline, previous.deadline);
  }
  return { deadline, durationMs: image.durationMs, label: image.label, seq: image.seq, url: image.url };
}

function restoreSpriteReaction(state: ChatStageState, snapshot: ChatSnapshot, receivedAt: number) {
  const reaction = snapshot.spriteReaction;
  if (!reaction?.text || !Number.isFinite(reaction.expiresAt) || !Number.isFinite(snapshot.serverTimeMs)) return null;
  const remaining = Math.min(reaction.durationMs, Math.max(0, reaction.expiresAt! - snapshot.serverTimeMs!));
  if (!Number.isFinite(remaining) || remaining <= 0) return null;
  let deadline = receivedAt + remaining;
  const previous = state.spriteReaction;
  if (state.sessionId === snapshot.sessionId && previous?.seq === reaction.seq && previous.text === reaction.text) {
    deadline = Math.min(deadline, previous.deadline);
  }
  return {
    characterName: reaction.characterName,
    deadline,
    durationMs: reaction.durationMs,
    seq: reaction.seq,
    text: reaction.text,
  };
}

function restoreBackgroundTransition(
  state: ChatStageState,
  snapshot: ChatSnapshot,
): ChatStageBackgroundTransition | null {
  const transition = snapshot.backgroundTransition;
  const effect = transition?.effect?.trim().toLowerCase() ?? "";
  if (
    !transition ||
    !effect ||
    typeof transition.expiresAt !== "number" ||
    !Number.isFinite(transition.expiresAt) ||
    typeof snapshot.serverTimeMs !== "number" ||
    !Number.isFinite(snapshot.serverTimeMs)
  ) {
    return null;
  }
  const durationMs =
    typeof transition.durationMs === "number" && Number.isFinite(transition.durationMs)
      ? Math.max(0, transition.durationMs)
      : 0;
  const remaining = Math.min(durationMs, Math.max(0, transition.expiresAt - snapshot.serverTimeMs));
  if (!Number.isFinite(remaining) || remaining <= 0) {
    return null;
  }
  const previous = state.backgroundTransition;
  if (state.sessionId === snapshot.sessionId && previous?.seq === transition.seq && previous.effect === effect) {
    return previous;
  }
  return { effect, seq: transition.seq };
}

function restoreSpriteMotions(state: ChatStageState, snapshot: ChatSnapshot): Record<string, ChatStageSpriteMotion> {
  const rawMotions = snapshot.spriteMotions;
  if (!rawMotions || typeof snapshot.serverTimeMs !== "number" || !Number.isFinite(snapshot.serverTimeMs)) {
    return {};
  }
  const serverTimeMs = snapshot.serverTimeMs;
  const restored: Record<string, ChatStageSpriteMotion> = {};
  for (const [name, entry] of Object.entries(rawMotions)) {
    const motion = entry?.motion?.trim().toLowerCase() ?? "";
    if (!name.trim() || !entry || !motion || typeof entry.expiresAt !== "number" || !Number.isFinite(entry.expiresAt)) {
      continue;
    }
    const durationMs = entry.durationMs && entry.durationMs > 0 ? entry.durationMs : 600;
    const remaining = Math.min(durationMs, Math.max(0, entry.expiresAt - serverTimeMs));
    if (!Number.isFinite(remaining) || remaining <= 0) {
      continue;
    }
    const previous = state.spriteMotions?.[name];
    if (state.sessionId === snapshot.sessionId && previous?.seq === entry.seq && previous.motion === motion) {
      restored[name] = previous;
    } else {
      restored[name] = { durationMs, motion, seq: entry.seq };
    }
  }
  return restored;
}

export function hydrateFromSnapshot(state: ChatStageState, snapshot: ChatSnapshot, receivedAt = 0): ChatStageState {
  if (snapshot.sessionId && state.sessionId && snapshot.sessionId !== state.sessionId) {
    state = emptyChatState;
  }
  const nextEventSeq = snapshotEventSeq(snapshot);
  if (nextEventSeq < state.eventSeq) {
    return state;
  }
  const transport = shouldPreserveTransportState(state)
    ? { transportMode: state.transportMode, transportState: state.transportState }
    : transportFromSnapshot(snapshot);
  const audioCommands = recoveryAudioCommands(state, snapshot, nextEventSeq);
  return withResolvedLayers({
    ...emptyChatState,
    ...snapshot,
    backgroundTransition: restoreBackgroundTransition(state, snapshot),
    effectImage: restoreEffectImage(state, snapshot, receivedAt),
    outfits: snapshot.outfits
      ? Object.fromEntries(Object.entries(snapshot.outfits).map(([key, value]) => [key, { ...value }]))
      : undefined,
    outfitCatalog: snapshot.outfitCatalog
      ? Object.fromEntries(
          Object.entries(snapshot.outfitCatalog).map(([key, value]) => [key, { ...value, groups: [...value.groups] }]),
        )
      : undefined,
    perception: snapshot.perception ? { ...snapshot.perception } : null,
    behavior: snapshot.behavior
      ? {
          ...snapshot.behavior,
          stagePolicy: { ...snapshot.behavior.stagePolicy },
        }
      : null,
    spriteMotions: restoreSpriteMotions(state, snapshot),
    spriteReaction: restoreSpriteReaction(state, snapshot, receivedAt),
    audioCommands,
    asrTranscript: undefined,
    error: undefined,
    eventSeq: nextEventSeq,
    inputAttachments: state.inputAttachments,
    inputDraft: state.inputDraft || snapshot.inputDraft,
    pluginPagePresentations: (snapshot.pluginPagePresentations ?? []).map((presentation) => ({
      ...presentation,
      payload: { ...presentation.payload },
    })),
    sprites: normalizeChatStageSprites(
      snapshot.sprites.map((sprite) => {
        const previous = state.sprites.find(
          (item) => chatStageSpriteCharacterName(item) === chatStageSpriteCharacterName(sprite),
        );
        const continuing =
          previous &&
          snapshot.sessionId &&
          state.sessionId === snapshot.sessionId &&
          (state.transportState === "connected" || state.transportState === "polling") &&
          !state.replay &&
          !snapshot.replay &&
          previous.avatarType !== "static" &&
          previous.avatarType === sprite.avatarType &&
          previous.modelUrl === sprite.modelUrl &&
          previous.path === sprite.path;
        return continuing
          ? { ...sprite, applyMode: previous.applyMode, stateSequence: previous.stateSequence }
          : { ...sprite, applyMode: "restore" as const };
      }),
    ),
    stats: (snapshot.stats ?? []).map((stat) => ({ ...stat })),
    toolConfirmation: snapshot.toolConfirmation ? { ...snapshot.toolConfirmation } : null,
    turnOptions: { ...emptyChatState.turnOptions, ...snapshot.turnOptions },
    turnState: {
      ...emptyChatState.turnState,
      ...snapshot.turnState,
      pendingMessages: [...(snapshot.turnState?.pendingMessages ?? [])],
    },
    ...transport,
  });
}
