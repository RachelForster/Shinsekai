import { describe, expect, it } from "vitest";

import { emptyChatState } from "../../../features/chat-stage/chatState";
import { applyStageEvent } from "../../../features/chat-stage/state/events";
import { stageEventHandlers } from "../../../features/chat-stage/state/eventHandlers";
import type { FoldedStageEventType } from "../../../features/chat-stage/state/eventHandlers/types";

const EXPECTED_FOLDED_EVENT_TYPES: readonly FoldedStageEventType[] = [
  "background.change",
  "bgm.change",
  "cg.show",
  "cg.hide",
  "sprite.show",
  "sprite.remove",
  "sprite.motion",
  "sprite.reaction",
  "player.portrait.show",
  "presentation.restore",
  "tts.play",
  "tts.skip",
  "effect.play",
  "effect.image.show",
  "effect.loop.start",
  "effect.loop.stop",
  "effect.loop.stop-all",
  "ambient.start",
  "ambient.layer",
  "ambient.stop",
  "ambient.stop-all",
  "dialog.end",
  "user.display_name.change",
  "options.show",
  "options.clear",
  "tool.confirmation.show",
  "tool.confirmation.clear",
  "history.replace",
  "chat.turn.state",
  "numeric.update",
  "stats.update",
  "busy.show",
  "busy.hide",
  "snapshot",
  "chat.init.progress",
  "chat.init.completed",
  "chat.init.failed",
  "chat.init.cancelled",
  "replay.state",
  "status.change",
  "notification.change",
  "reply.finished",
  "session.closed",
  "asr.partial",
  "asr.final",
  "asr.state",
  "perception.state",
  "perception.capture_request",
  "story.state.replace",
  "story.node.entered",
  "story.node.unlocked",
  "story.cast.replace",
  "story.ending.reached",
  "behavior.state.replace",
  "outfit.state",
  "memory.mode",
  "plugin.page.present",
  "plugin.page.dismiss",
];

describe("stageEventHandlers", () => {
  it("registers a concrete handler for every folded ChatStageEvent type", () => {
    expect(Object.keys(stageEventHandlers).sort()).toEqual([...EXPECTED_FOLDED_EVENT_TYPES].sort());
    for (const key of EXPECTED_FOLDED_EVENT_TYPES) {
      expect(typeof stageEventHandlers[key]).toBe("function");
    }
  });

  it("applies transport.state regardless of sequence and ignores stale non-snapshot events", () => {
    const withSeq = { ...emptyChatState, eventSeq: 10 };
    const transportUpdated = applyStageEvent(withSeq, {
      v: 1,
      seq: 1,
      ts: 100,
      type: "transport.state",
      transport: "websocket",
      state: "connected",
    });
    expect(transportUpdated.transportMode).toBe("websocket");
    expect(transportUpdated.transportState).toBe("connected");

    const stale = applyStageEvent(transportUpdated, {
      v: 1,
      seq: 10,
      ts: 101,
      type: "status.change",
      status: "generating",
    });
    expect(stale).toBe(transportUpdated);
  });

  it("ignores cmd.ack events without mutating stage state", () => {
    const withSeq = { ...emptyChatState, eventSeq: 5 };
    const next = applyStageEvent(withSeq, {
      v: 1,
      seq: 6,
      ts: 100,
      type: "cmd.ack",
      cmdId: "cmd-1",
      commandType: "send-message",
      ok: true,
    });
    expect(next).toBe(withSeq);
  });

  it("allows snapshot events even when envelope seq is not greater than state.eventSeq", () => {
    const withSeq = { ...emptyChatState, sessionId: "s1", eventSeq: 10 };
    const hydrated = applyStageEvent(
      withSeq,
      {
        v: 1,
        seq: 5,
        ts: 200,
        type: "snapshot",
        snapshot: {
          ...emptyChatState,
          effectImage: null,
          sessionId: "s1",
          eventSeq: 12,
          dialogText: "Hydrated",
        },
      },
      200,
    );
    expect(hydrated.eventSeq).toBe(12);
    expect(hydrated.dialogText).toBe("Hydrated");
  });

  it("dispatches domain handlers across audio, dialog, perception, and plugins", () => {
    let state = applyStageEvent(emptyChatState, {
      v: 1,
      seq: 1,
      ts: 10,
      type: "effect.play",
      url: "boom.wav",
    });
    expect(state.audioCommands).toEqual([{ kind: "effect-play", seq: 1, url: "boom.wav" }]);

    state = applyStageEvent(state, {
      v: 1,
      seq: 2,
      ts: 20,
      type: "perception.capture_request",
      reason: "manual",
    });
    expect(state.perceptionCaptureRequestSeq).toBe(2);

    state = applyStageEvent(state, {
      v: 1,
      seq: 3,
      ts: 30,
      type: "memory.mode",
      memoryMode: "shared",
    });
    expect(state.memoryMode).toBe("shared");

    state = applyStageEvent(state, {
      v: 1,
      seq: 4,
      ts: 40,
      type: "user.display_name.change",
      name: "Aoi",
    });
    expect(state.userDisplayName).toBe("Aoi");
  });

  it("retains at most 32 ambient effects on ambient.start", () => {
    let state = emptyChatState;
    for (let i = 1; i <= 35; i += 1) {
      state = applyStageEvent(state, {
        v: 1,
        seq: i,
        ts: i,
        type: "ambient.start",
        key: `ambient-${i}`,
        layer: "back",
        url: `/api/media?path=ambient-${i}.webm`,
      });
    }
    expect(state.ambientEffects).toHaveLength(32);
    expect(state.ambientEffects?.[0]?.key).toBe("ambient-4");
    expect(state.ambientEffects?.[31]?.key).toBe("ambient-35");
  });

  it.each([
    ["generating", "idle"],
    ["streaming", "idle"],
    ["speaking", "idle"],
    ["paused", "paused"],
    ["listening", "listening"],
  ] as const)("transitions %s -> %s on reply.finished", (initialStatus, expectedStatus) => {
    const state = applyStageEvent(
      {
        ...emptyChatState,
        status: initialStatus,
        activePlayback: { characterName: "Mio", playbackId: "p1", seq: 1, url: "v.wav", volume: 1 },
      },
      { v: 1, seq: 2, ts: 20, type: "reply.finished" },
    );
    expect(state.activePlayback).toBeNull();
    expect(state.status).toBe(expectedStatus);
  });

  it("removes sprites and motions matching characterName even when id and label differ", () => {
    const initial = {
      ...emptyChatState,
      sprites: [
        {
          id: "Mio:0",
          label: "Mio (Live)",
          characterName: "Mio",
          path: "mio.png",
          avatarType: "static",
          modelUrl: "",
        },
      ],
      spriteMotions: {
        "Mio:0": { durationMs: 500, motion: "nod", seq: 1 },
        "Mio (Live)": { durationMs: 500, motion: "nod", seq: 1 },
        Mio: { durationMs: 500, motion: "shake", seq: 2 },
      },
    };
    const next = applyStageEvent(initial, {
      v: 1,
      seq: 3,
      ts: 30,
      type: "sprite.remove",
      characterName: "Mio",
    });
    expect(next.sprites).toEqual([]);
    expect(next.spriteMotions).toEqual({});
  });
});
