import { describe, expect, it } from "vitest";

import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import { chatStageSpriteAxisCenter } from "../../../features/chat-stage/state/sprites";

describe("chatStageReducer", () => {
  it("applies background and BGM changes from the runtime stream", () => {
    const withBackground = chatStageReducer(emptyChatState, {
      event: {
        seq: 1,
        ts: 1,
        type: "background.change",
        url: "asset://night-street.png",
        v: 1,
      },
      type: "event",
    });
    const withBgm = chatStageReducer(withBackground, {
      event: {
        seq: 2,
        ts: 2,
        type: "bgm.change",
        url: "asset://night-theme.mp3",
        v: 1,
      },
      type: "event",
    });

    expect(withBgm.backgroundPath).toBe("asset://night-street.png");
    expect(withBgm.bgmPath).toBe("asset://night-theme.mp3");
    expect(buildChatStageViewModel(withBgm).bgmPath).toBe("asset://night-theme.mp3");
  });

  it("optimistically commits a user message and clears the input draft atomically", () => {
    const state = chatStageReducer(
      {
        ...emptyChatState,
        dialogHtml: "<p>old reply</p>",
        dialogText: "old reply",
        inputDraft: "hello",
        options: ["old option"],
        userDisplayName: "Aoi",
      },
      { text: "hello", type: "submitUserMessage" },
    );

    expect(state.characterName).toBe("Aoi");
    expect(state.dialogHtml).toBeUndefined();
    expect(state.dialogText).toBe("hello");
    expect(state.inputDraft).toBe("");
    expect(state.options).toEqual([]);
    expect(state.status).toBe("generating");
  });

  it("presents a backend ASR final transcript as an automatically submitted user turn", () => {
    const state = chatStageReducer(
      {
        ...emptyChatState,
        asrEnabled: true,
        asrRunning: true,
        inputDraft: "hello wor",
        status: "listening",
        userDisplayName: "Aoi",
      },
      {
        event: {
          seq: 1,
          text: "hello world",
          ts: 1,
          type: "asr.final",
          v: 1,
        },
        type: "event",
      },
    );

    expect(state.asrTranscript).toBe("hello world");
    expect(state.characterName).toBe("Aoi");
    expect(state.dialogText).toBe("hello world");
    expect(state.inputDraft).toBe("");
    expect(state.status).toBe("generating");
    expect(state.asrEnabled).toBe(true);
    expect(state.asrRunning).toBe(true);
    expect(state.optimisticSubmission?.text).toBe("hello world");
  });

  it("keeps ASR enabled while a character reply temporarily pauses capture", () => {
    const generating = {
      ...emptyChatState,
      asrEnabled: true,
      asrRunning: true,
      status: "generating" as const,
    };

    const pausedForReply = chatStageReducer(generating, {
      event: {
        enabled: true,
        loading: false,
        running: false,
        seq: 1,
        ts: 1,
        type: "asr.state",
        v: 1,
      },
      type: "event",
    });

    expect(pausedForReply.asrEnabled).toBe(true);
    expect(pausedForReply.asrLoading).toBe(false);
    expect(pausedForReply.asrRunning).toBe(false);
    expect(pausedForReply.status).toBe("generating");

    const resumed = chatStageReducer(pausedForReply, {
      event: {
        enabled: true,
        loading: false,
        running: true,
        seq: 2,
        ts: 2,
        type: "asr.state",
        v: 1,
      },
      type: "event",
    });

    expect(resumed.asrEnabled).toBe(true);
    expect(resumed.asrRunning).toBe(true);
    expect(resumed.status).toBe("listening");
  });

  it("hydrates an ASR-final snapshot without restoring a sendable draft", () => {
    const state = chatStageReducer(emptyChatState, {
      snapshot: {
        asrEnabled: true,
        asrRunning: false,
        dialogText: "",
        eventSeq: 4,
        inputDraft: "",
        options: [],
        sessionId: "session-1",
        sprites: [],
        status: "generating",
      },
      type: "hydrate",
    });

    expect(state.inputDraft).toBe("");
    expect(state.options).toEqual([]);
    expect(state.status).toBe("generating");
  });

  it("renders pending stacked messages as newline-separated user dialogue", () => {
    const viewModel = buildChatStageViewModel({
      ...emptyChatState,
      characterName: "Mio",
      dialogHtml: "<p>old reply</p>",
      dialogText: "old reply",
      turnState: {
        enabled: true,
        pendingCount: 2,
        pendingMessages: ["message A", "message B"],
        remainingSeconds: 4,
        scheduled: true,
        typing: false,
      },
      userDisplayName: "Aoi",
    });

    expect(viewModel.dialogCharacterName).toBe("Aoi");
    expect(viewModel.dialogHtml).toBeUndefined();
    expect(viewModel.dialogText).toBe("message A\nmessage B");
    expect(viewModel.layers.dialog).toBe(true);
  });

  it("rolls an optimistic option submission back to the previous presentation", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        characterName: "Mio",
        dialogText: "Choose",
        options: ["Left", "Right"],
      },
      { source: "submit-option", text: "Left", type: "submitUserMessage" },
    );

    const restored = chatStageReducer(submitted, {
      source: "submit-option",
      type: "rollbackUserSubmission",
    });

    expect(restored.characterName).toBe("Mio");
    expect(restored.dialogText).toBe("Choose");
    expect(restored.options).toEqual(["Left", "Right"]);
    expect(restored.status).toBe("idle");
    expect(restored.optimisticSubmission).toBeUndefined();
  });

  it("preserves a new draft when an earlier submission fails late", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        characterName: "Mio",
        dialogText: "Previous reply",
        inputDraft: "first message",
        options: ["Left", "Right"],
        userDisplayName: "Aoi",
      },
      { source: "send-message", text: "first message", type: "submitUserMessage" },
    );
    const withNextDraft = chatStageReducer(submitted, { text: "next message", type: "setDraft" });
    const restored = chatStageReducer(withNextDraft, {
      source: "send-message",
      type: "rollbackUserSubmission",
    });

    expect(restored.characterName).toBe("Mio");
    expect(restored.dialogText).toBe("Previous reply");
    expect(restored.options).toEqual(["Left", "Right"]);
    expect(restored.status).toBe("idle");
    expect(restored.inputDraft).toBe("next message");
    expect(restored.optimisticSubmission).toBeUndefined();
  });

  it("clears attachments optimistically and restores them when sending fails", () => {
    const attachment = { kind: "image" as const, name: "scene.png", path: "D:/scene.png" };
    const submitted = chatStageReducer(
      { ...emptyChatState, inputAttachments: [attachment], inputDraft: "Inspect" },
      { source: "send-message", text: "Inspect\n[image: scene.png]", type: "submitUserMessage" },
    );

    expect(submitted.inputAttachments).toEqual([]);
    const restored = chatStageReducer(submitted, {
      source: "send-message",
      type: "rollbackUserSubmission",
    });

    expect(restored.inputAttachments).toEqual([attachment]);
    expect(restored.inputDraft).toBe("Inspect");
  });

  it("does not roll back a submission after a newer authoritative event", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        dialogText: "Choose",
        eventSeq: 1,
        options: ["Left", "Right"],
      },
      { source: "submit-option", text: "Left", type: "submitUserMessage" },
    );
    const replied = chatStageReducer(submitted, {
      event: {
        color: "#fff",
        fullHtml: "<p>Accepted</p>",
        isSystem: false,
        seq: 2,
        speaker: "Mio",
        ts: 2,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });

    const lateRollback = chatStageReducer(replied, {
      source: "submit-option",
      type: "rollbackUserSubmission",
    });

    expect(lateRollback.characterName).toBe("Mio");
    expect(lateRollback.dialogText).toBe("Accepted");
    expect(lateRollback.options).toEqual([]);
    expect(lateRollback.optimisticSubmission).toBeUndefined();
  });

  it("keeps an optimistic user message through unrelated runtime events and stale snapshots", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        characterName: "Mio",
        dialogText: "old reply",
        eventSeq: 3,
        inputDraft: "hello",
        sprites: [],
        userDisplayName: "Aoi",
      },
      { source: "send-message", text: "hello", type: "submitUserMessage" },
    );
    const withStatus = chatStageReducer(submitted, {
      event: { seq: 4, status: "generating", ts: 4, type: "status.change", v: 1 },
      type: "event",
    });
    const withHistory = chatStageReducer(withStatus, {
      event: {
        entries: [{ id: "user-1", role: "user", text: "Aoi: hello" }],
        seq: 5,
        ts: 5,
        type: "history.replace",
        v: 1,
      },
      type: "event",
    });
    const staleSnapshot = chatStageReducer(withHistory, {
      event: {
        seq: 5,
        snapshot: {
          characterName: "Mio",
          dialogText: "old reply",
          eventSeq: 3,
          inputDraft: "",
          options: [],
          sessionId: "session-1",
          sprites: [],
          status: "idle",
        },
        ts: 5,
        type: "snapshot",
        v: 1,
      },
      type: "event",
    });

    expect(staleSnapshot.characterName).toBe("Aoi");
    expect(staleSnapshot.dialogText).toBe("hello");
    expect(staleSnapshot.status).toBe("generating");
    expect(staleSnapshot.optimisticSubmission?.text).toBe("hello");
    expect(staleSnapshot.historyEntries).toEqual([{ id: "user-1", role: "user", text: "Aoi: hello" }]);
  });

  it("keeps the optimistic user message when a seq-advanced snapshot still carries the previous reply", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        characterName: "Mio",
        dialogText: "old reply",
        eventSeq: 3,
        inputDraft: "hello",
        sprites: [],
        userDisplayName: "Aoi",
      },
      { source: "send-message", text: "hello", type: "submitUserMessage" },
    );
    const withStatus = chatStageReducer(submitted, {
      event: { seq: 4, status: "generating", ts: 4, type: "status.change", v: 1 },
      type: "event",
    });
    // The reply has not been generated yet, but the backend republishes a snapshot
    // whose eventSeq has advanced past the current state while its dialogue is still
    // the pre-submit line. It must not flash the previous turn's reply.
    const staleAhead = chatStageReducer(withStatus, {
      event: {
        seq: 7,
        snapshot: {
          characterName: "Mio",
          dialogText: "old reply",
          eventSeq: 7,
          inputDraft: "",
          options: [],
          sessionId: "session-1",
          sprites: [],
          status: "idle",
        },
        ts: 7,
        type: "snapshot",
        v: 1,
      },
      type: "event",
    });

    expect(staleAhead.characterName).toBe("Aoi");
    expect(staleAhead.dialogText).toBe("hello");
    expect(staleAhead.status).toBe("generating");
    expect(staleAhead.optimisticSubmission?.text).toBe("hello");

    // Once a genuinely new reply lands, it replaces the optimistic user message.
    const freshReply = chatStageReducer(staleAhead, {
      event: {
        seq: 8,
        snapshot: {
          characterName: "Mio",
          dialogText: "brand new reply",
          eventSeq: 8,
          inputDraft: "",
          options: [],
          sessionId: "session-1",
          sprites: [],
          status: "idle",
        },
        ts: 8,
        type: "snapshot",
        v: 1,
      },
      type: "event",
    });

    expect(freshReply.characterName).toBe("Mio");
    expect(freshReply.dialogText).toBe("brand new reply");
    expect(freshReply.optimisticSubmission).toBeUndefined();
  });

  it("accepts a newer wrapped snapshot when its payload omits eventSeq", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        characterName: "Mio",
        dialogText: "old reply",
        eventSeq: 2,
        inputDraft: "hello",
        userDisplayName: "Aoi",
      },
      { queued: true, source: "send-message", text: "hello", type: "submitUserMessage" },
    );
    const pending = chatStageReducer(submitted, {
      event: {
        seq: 3,
        snapshot: {
          characterName: "Mio",
          dialogText: "old reply",
          inputDraft: "",
          options: [],
          sprites: [],
          status: "idle",
          turnState: {
            enabled: true,
            pendingCount: 1,
            remainingSeconds: 5,
            scheduled: true,
            typing: false,
          },
        },
        ts: 3,
        type: "snapshot",
        v: 1,
      },
      type: "event",
    });

    expect(pending.eventSeq).toBe(3);
    expect(pending.turnState).toMatchObject({ pendingCount: 1, scheduled: true });
  });

  it.each(["send-message", "submit-option"] as const)(
    "keeps the first %s submission through a newer startup feedback snapshot",
    (source) => {
      const submitted = chatStageReducer(
        {
          ...emptyChatState,
          characterName: "",
          dialogText: "Chat started",
          eventSeq: 1,
          options: source === "submit-option" ? ["Take the shortcut"] : [],
          statusMessage: "Chat started",
          userDisplayName: "Aoi",
        },
        { source, text: source === "submit-option" ? "Take the shortcut" : "hello", type: "submitUserMessage" },
      );
      const startupSnapshot = chatStageReducer(submitted, {
        event: {
          seq: 2,
          snapshot: {
            characterName: "Mio",
            dialogText: "Chat started",
            eventSeq: 2,
            inputDraft: "",
            options: [],
            sprites: [],
            status: "generating",
            statusMessage: "Chat started",
            userDisplayName: "Aoi",
          },
          ts: 2,
          type: "snapshot",
          v: 1,
        },
        type: "event",
      });
      const viewModel = buildChatStageViewModel(startupSnapshot);

      expect(startupSnapshot.optimisticSubmission?.source).toBe(source);
      expect(viewModel.dialogCharacterName).toBe("Aoi");
      expect(viewModel.dialogText).toBe(source === "submit-option" ? "Take the shortcut" : "hello");
      expect(viewModel.layers.dialog).toBe(true);
      expect(viewModel.layers.notification).toBe(false);
    },
  );

  it("uses the default user name and removes startup feedback from a first submission", () => {
    const submitted = chatStageReducer(
      {
        ...emptyChatState,
        dialogText: "Chat started",
        statusMessage: "Chat started",
        userDisplayName: "",
      },
      { source: "send-message", text: "hello", type: "submitUserMessage" },
    );
    const viewModel = buildChatStageViewModel(submitted);

    expect(submitted.characterName).toBe(viewModel.userDisplayName);
    expect(submitted.statusMessage).toBeUndefined();
    expect(viewModel.dialogText).toBe("hello");
    expect(viewModel.layers.dialog).toBe(true);
    expect(viewModel.layers.notification).toBe(false);
  });

  it("keeps an optimistic user message when a late initial hydration resolves", () => {
    const submitted = chatStageReducer(
      { ...emptyChatState, eventSeq: 3, inputDraft: "hello", userDisplayName: "Aoi" },
      { source: "send-message", text: "hello", type: "submitUserMessage" },
    );
    const hydrated = chatStageReducer(submitted, {
      snapshot: {
        characterName: "Mio",
        dialogText: "old reply",
        eventSeq: 4,
        inputDraft: "",
        options: [],
        sessionId: "session-1",
        sprites: [],
        status: "idle",
      },
      type: "hydrate",
    });

    expect(hydrated.characterName).toBe("Aoi");
    expect(hydrated.dialogText).toBe("hello");
    expect(hydrated.optimisticSubmission?.text).toBe("hello");
  });

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

  it("retains chat initialization task events for reconnect diagnostics", () => {
    const state = chatStageReducer(emptyChatState, {
      event: {
        seq: 1,
        task: {
          createdAt: 1,
          id: "child-init",
          kind: "chat-initialization",
          logs: [],
          message: "Starting voice service.",
          phase: "tts.init",
          progress: 0.42,
          result: null,
          status: "running",
          title: "Starting chat",
          updatedAt: 2,
        },
        ts: 2,
        type: "chat.init.progress",
        v: 1,
      },
      type: "event",
    });

    expect(state.initTask).toMatchObject({ phase: "tts.init", progress: 0.42, status: "running" });
  });

  it("projects stage events into layer visibility state", () => {
    const clearedState = chatStageReducer(
      { ...emptyChatState, sprites: [{ id: "stale", label: "Stale", path: "asset://stale.png" }] },
      {
        snapshot: {
          dialogText: "",
          eventSeq: 0,
          inputDraft: "",
          options: [],
          sprites: [],
          status: "idle",
        },
        type: "hydrate",
      },
    );
    expect(clearedState.sprites).toEqual([]);

    const spriteState = chatStageReducer(clearedState, {
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

  it("projects user dialog text into a custom nameplate and pure body text", () => {
    const state = chatStageReducer(emptyChatState, {
      snapshot: {
        characterName: "",
        dialogText: "你：这是一句用户输入",
        eventSeq: 1,
        inputDraft: "",
        options: [],
        sprites: [],
        status: "generating",
        userDisplayName: "澪",
      },
      type: "hydrate",
    });

    const viewModel = buildChatStageViewModel(state);

    expect(viewModel.dialogCharacterName).toBe("澪");
    expect(viewModel.dialogText).toBe("这是一句用户输入");
  });

  it("applies user display name events to the nameplate", () => {
    const state = chatStageReducer(emptyChatState, {
      event: {
        name: "澪",
        seq: 1,
        ts: 1,
        type: "user.display_name.change",
        v: 1,
      },
      type: "event",
    });

    expect(buildChatStageViewModel(state).userDisplayName).toBe("澪");
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
    expect(withOptions.layers.dialog).toBe(false);

    const firstLine = chatStageReducer(withOptions, {
      event: {
        color: "#84C2D5",
        fullHtml: "<p><b>旁白</b>：正式首句</p>",
        isSystem: true,
        seq: 3,
        speaker: "旁白",
        ts: 3,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });
    expect(firstLine.options).toEqual([]);
    expect(firstLine.layers.options).toBe(false);

    const cleared = chatStageReducer(firstLine, {
      event: {
        seq: 4,
        ts: 4,
        type: "options.clear",
        v: 1,
      },
      type: "event",
    });
    expect(cleared.options).toEqual([]);
    expect(cleared.layers.options).toBe(false);

    const hidden = chatStageReducer(cleared, {
      event: {
        seq: 5,
        ts: 5,
        type: "busy.hide",
        v: 1,
      },
      type: "event",
    });
    expect(hidden.busyText).toBeUndefined();
    expect(hidden.layers.busy).toBe(false);
  });

  it("updates token usage text and clears sprites by character name", () => {
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
        x: 24,
        y: -18,
      },
      type: "event",
    });
    expect(withSprite.layers.sprites).toBe(true);
    expect(withSprite.sprites).toHaveLength(1);
    expect(withSprite.sprites[0]).toEqual(
      expect.objectContaining({
        x: 24,
        y: -18,
      }),
    );

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
    expect(viewModel.statusText).toBe("idle");
    expect(viewModel.tokenUsageText).toBe("tokens\n42");

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

  it("keeps structured character stats separate from token usage", () => {
    const withStats = chatStageReducer(emptyChatState, {
      event: {
        seq: 1,
        stats: [
          { icon: "heart", label: "HP", max: 100, value: 72 },
          { icon: "coins", label: "Gold", value: 320 },
        ],
        ts: 1,
        type: "stats.update",
        v: 1,
      },
      type: "event",
    });

    const viewModel = buildChatStageViewModel(withStats);
    expect(viewModel.stats).toEqual([
      { icon: "heart", label: "HP", max: 100, value: 72 },
      { icon: "coins", label: "Gold", value: 320 },
    ]);
    expect(viewModel.tokenUsageText).toBeUndefined();
  });

  it("keeps expression changes in the same display slot and evicts slots by LRU", () => {
    const showSprite = (
      state: typeof emptyChatState,
      seq: number,
      characterName: string,
      slot: number,
      url = `asset://${characterName}-${seq}.png`,
    ) =>
      chatStageReducer(state, {
        event: {
          characterName,
          scale: 1,
          seq,
          slot,
          ts: seq,
          type: "sprite.show",
          url,
          v: 1,
        },
        type: "event",
      });

    const mio = showSprite(emptyChatState, 1, "Mio", 2);
    const mioExpression = showSprite(mio, 2, "Mio", 1, "asset://mio-happy.png");
    expect(mioExpression.sprites).toHaveLength(1);
    expect(mioExpression.sprites[0]).toEqual(
      expect.objectContaining({
        id: "Mio",
        path: "asset://mio-happy.png",
        slot: 0,
      }),
    );

    const ren = showSprite(mioExpression, 3, "Ren", 0);
    const nanami = showSprite(ren, 4, "Nanami", 0);
    const refreshedMio = showSprite(nanami, 5, "Mio", 0);
    const aoi = showSprite(refreshedMio, 6, "Aoi", 1);

    expect(aoi.sprites.map((sprite) => sprite.characterName)).toEqual(["Nanami", "Mio", "Aoi"]);
    expect(aoi.sprites.map((sprite) => sprite.slot)).toEqual([2, 0, 1]);
  });

  it("preserves snapshot LRU order so the most recent sprite stays in front", () => {
    const hydrated = chatStageReducer(emptyChatState, {
      snapshot: {
        dialogText: "",
        eventSeq: 3,
        inputDraft: "",
        options: [],
        sprites: [
          { id: "Aoi:2", label: "Aoi", path: "asset://aoi.png", slot: 2 },
          { id: "Mio:0", label: "Mio", path: "asset://mio-happy.png", slot: 0 },
        ],
        status: "idle",
      },
      type: "hydrate",
    });

    expect(hydrated.sprites.map((sprite) => sprite.label)).toEqual(["Aoi", "Mio"]);
    expect(hydrated.sprites.map((sprite) => sprite.slot)).toEqual([2, 0]);
  });

  it("centers occupied sprite axes with the legacy Qt compensation", () => {
    const left = { id: "Mio", label: "Mio", path: "mio.png", slot: 0 };
    const middle = { id: "Ren", label: "Ren", path: "ren.png", slot: 1 };
    const right = { id: "Aoi", label: "Aoi", path: "aoi.png", slot: 2 };

    expect(chatStageSpriteAxisCenter([left], left, 0)).toBe(50);
    expect(chatStageSpriteAxisCenter([left, middle], left, 0)).toBeCloseTo(100 / 3);
    expect(chatStageSpriteAxisCenter([left, middle], middle, 1)).toBeCloseTo(200 / 3);
    expect(chatStageSpriteAxisCenter([left, middle, right], right, 2)).toBeCloseTo(250 / 3);
  });

  it("ignores runtime status labels when building token usage text", () => {
    const streaming = chatStageReducer(emptyChatState, {
      event: {
        seq: 1,
        status: "streaming",
        ts: 1,
        type: "status.change",
        v: 1,
      },
      type: "event",
    });
    const withStatusNumeric = chatStageReducer(streaming, {
      event: {
        html: "streaming",
        seq: 2,
        ts: 2,
        type: "numeric.update",
        v: 1,
      },
      type: "event",
    });

    expect(buildChatStageViewModel(withStatusNumeric).tokenUsageText).toBeUndefined();
    expect(buildChatStageViewModel(withStatusNumeric).statusText).toBe("streaming");
  });

  it("projects command feedback into notifications instead of the dialog layer", () => {
    const state = chatStageReducer(emptyChatState, {
      snapshot: {
        characterName: "",
        dialogText: "已跳过当前语音。",
        eventSeq: 1,
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
        statusMessage: "已跳过当前语音。",
      },
      type: "hydrate",
    });

    const viewModel = buildChatStageViewModel(state);

    expect(viewModel.layers.dialog).toBe(false);
    expect(viewModel.dialogText).toBe("");
    expect(viewModel.layers.notification).toBe(true);
    expect(viewModel.notificationText).toBe("已跳过当前语音。");
  });

  it("routes speakerless system dialog events to notifications", () => {
    const state = chatStageReducer(emptyChatState, {
      event: {
        color: "#fff",
        fullHtml: "<p>等待对话开始</p>",
        isSystem: true,
        seq: 1,
        speaker: "",
        ts: 1,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });

    const viewModel = buildChatStageViewModel(state);

    expect(viewModel.layers.dialog).toBe(false);
    expect(viewModel.notificationText).toBe("等待对话开始");

    const afterStatus = chatStageReducer(state, {
      event: {
        seq: 2,
        status: "idle",
        ts: 2,
        type: "status.change",
        v: 1,
      },
      type: "event",
    });
    expect(buildChatStageViewModel(afterStatus).notificationText).toBe("等待对话开始");
  });

  it("hydrates folded system messages and clears them after dialogue or session close", () => {
    const hydrated = chatStageReducer(emptyChatState, {
      snapshot: {
        characterName: "",
        dialogHtml: "<p>Waiting for chat</p>",
        dialogText: "Waiting for chat",
        eventSeq: 1,
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
        systemMessageText: "Waiting for chat",
      },
      type: "hydrate",
    });
    const systemView = buildChatStageViewModel(hydrated);

    expect(systemView.notificationText).toBe("Waiting for chat");
    expect(systemView.layers.notification).toBe(true);
    expect(systemView.layers.dialog).toBe(false);

    const withDialogue = chatStageReducer(hydrated, {
      event: {
        color: "#fff",
        fullHtml: "<p>Ready now</p>",
        isSystem: false,
        seq: 2,
        speaker: "Mio",
        ts: 2,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });
    expect(withDialogue.systemMessageText).toBeUndefined();
    expect(buildChatStageViewModel(withDialogue).layers.dialog).toBe(true);

    const closed = chatStageReducer(hydrated, {
      event: { reason: "Closed", seq: 2, ts: 2, type: "session.closed", v: 1 },
      type: "event",
    });
    expect(closed.systemMessageText).toBeUndefined();
    expect(buildChatStageViewModel(closed).notificationText).toBe("Closed");
  });

  it("keeps named system narrators in the dialog layer", () => {
    const state = chatStageReducer(emptyChatState, {
      event: {
        color: "#fff",
        fullHtml: "<p><b>旁白</b>：等待对话开始</p>",
        isSystem: true,
        seq: 1,
        speaker: "旁白",
        ts: 1,
        type: "dialog.end",
        v: 1,
      },
      type: "event",
    });

    const viewModel = buildChatStageViewModel(state);

    expect(viewModel.layers.dialog).toBe(true);
    expect(viewModel.dialogCharacterName).toBe("旁白");
    expect(viewModel.dialogText).toContain("等待对话开始");
    expect(viewModel.layers.notification).toBe(false);
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

  it("applies live chat turn state events", () => {
    const next = chatStageReducer(emptyChatState, {
      event: {
        seq: 1,
        options: {
          batchEnabled: true,
          batchIdleSeconds: 7,
          interruptEnabled: false,
        },
        state: {
          enabled: true,
          pendingCount: 3,
          pendingMessages: ["one", "two", "three"],
          remainingSeconds: 2,
          scheduled: true,
          typing: false,
        },
        ts: 1,
        type: "chat.turn.state",
        v: 1,
      },
      type: "event",
    });

    expect(next.turnState).toEqual({
      enabled: true,
      pendingCount: 3,
      pendingMessages: ["one", "two", "three"],
      remainingSeconds: 2,
      scheduled: true,
      typing: false,
    });
    expect(next.turnOptions).toEqual({
      batchEnabled: true,
      batchIdleSeconds: 7,
      interruptEnabled: false,
    });
  });
});
