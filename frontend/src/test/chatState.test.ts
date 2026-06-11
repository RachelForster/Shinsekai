import { describe, expect, it } from "vitest";

import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "../features/chat-stage/chatState";

describe("chatStageReducer", () => {
  it("hydrates runtime snapshots from platform events", () => {
    const state = chatStageReducer(emptyChatState, {
      snapshot: {
        dialogText: "hello",
        eventSeq: 3,
        inputDraft: "",
        options: ["继续"],
        sessionId: "session-1",
        sprites: [],
        status: "streaming",
        wsUrl: "ws://127.0.0.1:8788/ws",
      },
      type: "hydrate",
    });

    expect(state.dialogText).toBe("hello");
    expect(state.eventSeq).toBe(3);
    expect(state.status).toBe("streaming");
    expect(state.options).toEqual(["继续"]);
    expect(state.transportMode).toBe("websocket");
    expect(state.transportState).toBe("connecting");
  });

  it("keeps transient input draft local until submit", () => {
    const state = chatStageReducer(emptyChatState, { text: "draft", type: "setDraft" });
    expect(state.inputDraft).toBe("draft");
    expect(state.status).toBe("idle");
  });

  it("projects stage events into layer visibility state", () => {
    const spriteState = chatStageReducer(emptyChatState, {
      event: {
        characterName: "Mio",
        scale: 1.1,
        seq: 1,
        ts: 1,
        type: "sprite.show",
        url: "asset://mio.png",
        v: 1,
      },
      type: "event",
    });
    expect(spriteState.layers.sprites).toBe(true);
    expect(spriteState.sprites[0]?.label).toBe("Mio");

    const cgState = chatStageReducer(spriteState, {
      event: {
        seq: 2,
        ts: 2,
        type: "cg.show",
        url: "asset://cg.png",
        v: 1,
      },
      type: "event",
    });
    expect(cgState.layers.cg).toBe(true);
    expect(cgState.layers.sprites).toBe(false);

    const closedState = chatStageReducer(cgState, {
      event: {
        reason: "Closed",
        seq: 3,
        ts: 3,
        type: "session.closed",
        v: 1,
      },
      type: "event",
    });
    expect(closedState.layers.input).toBe(false);
    expect(closedState.layers.options).toBe(false);
    expect(closedState.notificationText).toBe("Closed");
  });

  it("reopens the input layer when hydrate clears closed-session markers", () => {
    const closedState = chatStageReducer(emptyChatState, {
      snapshot: {
        dialogText: "聊天会话已结束。",
        eventSeq: 3,
        inputDraft: "",
        notificationText: "聊天会话已结束。",
        options: [],
        sessionClosedReason: "聊天会话已结束。",
        sprites: [],
        status: "paused",
      },
      type: "hydrate",
    });
    expect(closedState.layers.input).toBe(false);
    expect(closedState.layers.notification).toBe(true);

    const reopenedState = chatStageReducer(closedState, {
      snapshot: {
        dialogText: "语音识别已恢复。",
        eventSeq: 4,
        inputDraft: "",
        notificationText: "",
        options: [],
        sessionClosedReason: "",
        sprites: [],
        status: "listening",
      },
      type: "hydrate",
    });

    expect(reopenedState.layers.input).toBe(true);
    expect(reopenedState.layers.notification).toBe(false);
    expect(reopenedState.notificationText).toBe("");
    expect(reopenedState.sessionClosedReason).toBe("");
  });

  it("builds a stable view model from state", () => {
    const state = chatStageReducer(emptyChatState, {
      event: {
        color: "#fff",
        fullHtml: "<p>Hello<br>world</p>",
        isSystem: false,
        seq: 1,
        speaker: "Nanami",
        ts: 1,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });

    const viewModel = buildChatStageViewModel(state);

    expect(viewModel.dialogCharacterName).toBe("Nanami");
    expect(viewModel.dialogHtml).toContain("Hello");
    expect(viewModel.dialogText).toBe("Hello\nworld");
    expect(viewModel.layers.dialog).toBe(true);
    expect(viewModel.inputDisabled).toBe(false);
    expect(viewModel.transportMode).toBe("snapshot");
    expect(viewModel.transportState).toBe("connecting");
  });

  it("tracks transport state separately from business runtime status", () => {
    const hydrated = chatStageReducer(emptyChatState, {
      snapshot: {
        dialogText: "hello",
        eventSeq: 1,
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
      },
      type: "hydrate",
    });
    const connected = chatStageReducer(hydrated, {
      event: {
        seq: 1,
        state: "connected",
        transport: "websocket",
        ts: 1,
        type: "transport.state",
        v: 1,
      },
      type: "event",
    });

    expect(connected.status).toBe("idle");
    expect(connected.transportMode).toBe("websocket");
    expect(connected.transportState).toBe("connected");
  });

  it("preserves an observed transport state across later snapshot hydrates", () => {
    const connected = chatStageReducer(emptyChatState, {
      event: {
        seq: 0,
        state: "polling",
        transport: "snapshot",
        ts: 1,
        type: "transport.state",
        v: 1,
      },
      type: "event",
    });

    const hydrated = chatStageReducer(connected, {
      snapshot: {
        dialogText: "hello",
        eventSeq: 0,
        inputDraft: "",
        options: [],
        sessionId: "session-1",
        sprites: [],
        status: "idle",
        wsUrl: "ws://127.0.0.1:8788/ws",
      },
      type: "hydrate",
    });

    expect(hydrated.transportMode).toBe("snapshot");
    expect(hydrated.transportState).toBe("polling");
  });

  it("ignores stale snapshots and stale events after recovery", () => {
    const recovered = chatStageReducer(emptyChatState, {
      snapshot: {
        backgroundPath: "asset://new-bg.png",
        dialogText: "recovered",
        eventSeq: 7,
        inputDraft: "",
        options: ["继续"],
        sprites: [],
        status: "idle",
      },
      type: "hydrate",
    });

    const staleEvent = chatStageReducer(recovered, {
      event: {
        seq: 6,
        text: "old notification",
        ts: 6,
        type: "notification.change",
        v: 1,
      },
      type: "event",
    });
    expect(staleEvent.notificationText).toBeUndefined();
    expect(staleEvent.dialogText).toBe("recovered");

    const staleSnapshot = chatStageReducer(recovered, {
      snapshot: {
        backgroundPath: "asset://old-bg.png",
        dialogText: "stale",
        eventSeq: 5,
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
      },
      type: "hydrate",
    });
    expect(staleSnapshot.backgroundPath).toBe("asset://new-bg.png");
    expect(staleSnapshot.dialogText).toBe("recovered");
  });

  it("drives layer visibility from control events", () => {
    const withControls = chatStageReducer(emptyChatState, {
      event: {
        durationSeconds: 1.5,
        seq: 1,
        text: "Loading",
        ts: 1,
        type: "busy.show",
        v: 1,
      },
      type: "event",
    });
    expect(withControls.busyText).toBe("Loading");
    expect(withControls.layers.busy).toBe(true);

    const withOptions = chatStageReducer(withControls, {
      event: {
        options: ["继续"],
        seq: 2,
        ts: 2,
        type: "options.show",
        v: 1,
      },
      type: "event",
    });
    expect(withOptions.options).toEqual(["继续"]);
    expect(withOptions.layers.options).toBe(true);

    const cleared = chatStageReducer(withOptions, {
      event: {
        seq: 3,
        ts: 3,
        type: "options.clear",
        v: 1,
      },
      type: "event",
    });
    expect(cleared.options).toEqual([]);
    expect(cleared.layers.options).toBe(false);

    const hidden = chatStageReducer(cleared, {
      event: {
        seq: 4,
        ts: 4,
        type: "busy.hide",
        v: 1,
      },
      type: "event",
    });
    expect(hidden.busyText).toBeUndefined();
    expect(hidden.layers.busy).toBe(false);
  });

  it("updates numeric status text and clears sprites by character name", () => {
    const withSprite = chatStageReducer(emptyChatState, {
      event: {
        characterName: "Mio",
        scale: 1.1,
        seq: 1,
        slot: 0,
        ts: 1,
        type: "sprite.show",
        url: "asset://mio.png",
        v: 1,
      },
      type: "event",
    });
    expect(withSprite.layers.sprites).toBe(true);
    expect(withSprite.sprites).toHaveLength(1);

    const withNumeric = chatStageReducer(withSprite, {
      event: {
        html: "<b>tokens</b><br>42",
        seq: 2,
        ts: 2,
        type: "numeric.update",
        v: 1,
      },
      type: "event",
    });
    const viewModel = buildChatStageViewModel(withNumeric);
    expect(viewModel.statusText).toBe("tokens\n42");

    const withoutSprite = chatStageReducer(withNumeric, {
      event: {
        characterName: "Mio",
        seq: 3,
        ts: 3,
        type: "sprite.remove",
        v: 1,
      },
      type: "event",
    });
    expect(withoutSprite.sprites).toEqual([]);
    expect(withoutSprite.layers.sprites).toBe(false);
  });

  it("lets reply.finished and status.change control runtime status without fighting each other", () => {
    const generating = chatStageReducer(emptyChatState, {
      type: "setStatus",
      status: "generating",
    });

    const finished = chatStageReducer(generating, {
      event: {
        seq: 1,
        ts: 1,
        type: "reply.finished",
        v: 1,
      },
      type: "event",
    });
    expect(finished.status).toBe("idle");
    expect(finished.notificationText).toBeUndefined();

    const paused = chatStageReducer(finished, {
      event: {
        seq: 2,
        status: "paused",
        ts: 2,
        type: "status.change",
        v: 1,
      },
      type: "event",
    });
    expect(paused.status).toBe("paused");
    expect(paused.notificationText).toBeUndefined();

    const finishedWhilePaused = chatStageReducer(paused, {
      event: {
        seq: 3,
        ts: 3,
        type: "reply.finished",
        v: 1,
      },
      type: "event",
    });
    expect(finishedWhilePaused.status).toBe("paused");
  });

  it("clears transient notifications when interaction resumes through runtime events", () => {
    const withNotification = chatStageReducer(emptyChatState, {
      event: {
        seq: 1,
        text: "您的消息已提交，正在等待 LLM 处理...",
        ts: 1,
        type: "notification.change",
        v: 1,
      },
      type: "event",
    });
    expect(withNotification.layers.notification).toBe(true);

    const reopenedByDialog = chatStageReducer(withNotification, {
      event: {
        color: "#fff",
        fullHtml: "<p>收到消息：恢复后继续</p>",
        isSystem: false,
        seq: 2,
        speaker: "Nanami",
        ts: 2,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });
    expect(reopenedByDialog.notificationText).toBeUndefined();
    expect(reopenedByDialog.layers.notification).toBe(false);

    const withNotificationAgain = chatStageReducer(withNotification, {
      event: {
        seq: 3,
        ts: 3,
        type: "reply.finished",
        v: 1,
      },
      type: "event",
    });
    expect(withNotificationAgain.notificationText).toBeUndefined();
    expect(withNotificationAgain.layers.notification).toBe(false);
  });
});
