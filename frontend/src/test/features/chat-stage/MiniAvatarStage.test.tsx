/// <reference types="vitest/jsdom" />

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import {
  MINI_AVATAR_HOVER_HIDE_MS,
  MINI_AVATAR_IDLE_BUBBLE_HIDE_MS,
  MiniAvatarStage,
  resolveMiniAvatarSpeaker,
} from "../../../features/chat-stage/components/MiniAvatarStage";
import type { ChatStageSprite } from "../../../features/chat-stage/state/types";
import { registerAvatarFormat, routeAvatarVoice } from "../../../modules/character-visual";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { createHttpPlatform } from "../../../shared/platform/httpPlatform";
import type { ChatSnapshot, ChatStageEvent, ShinsekaiPlatform } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const platformMocks = vi.hoisted(() => ({
  getPlatform: vi.fn<() => ShinsekaiPlatform>(),
}));

const desktopApiMocks = vi.hoisted(() => ({
  closeDesktopWindow: vi.fn(),
  getDesktopWindowCursorState: vi.fn(),
  isDesktopChatWindow: vi.fn(),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn(),
  setDesktopChatWindowMiniMode: vi.fn(),
  setDesktopWindowAlwaysOnTop: vi.fn(),
  setDesktopWindowClickThrough: vi.fn(),
  startDesktopWindowDrag: vi.fn(),
  syncDesktopChatWindowMiniLayout: vi.fn(),
  toggleMaximizeDesktopWindow: vi.fn(),
}));

vi.mock("../../../shared/platform/platform", () => ({
  getPlatform: () => platformMocks.getPlatform(),
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    closeDesktopWindow: () => desktopApiMocks.closeDesktopWindow(),
    getDesktopWindowCursorState: () => desktopApiMocks.getDesktopWindowCursorState(),
    isDesktopChatWindow: () => desktopApiMocks.isDesktopChatWindow(),
    isTauriDesktop: () => desktopApiMocks.isTauriDesktop(),
    minimizeDesktopWindow: () => desktopApiMocks.minimizeDesktopWindow(),
    setDesktopChatWindowMiniMode: (mini: boolean, restoreAlwaysOnTop: boolean) =>
      desktopApiMocks.setDesktopChatWindowMiniMode(mini, restoreAlwaysOnTop),
    setDesktopWindowAlwaysOnTop: (alwaysOnTop: boolean) => desktopApiMocks.setDesktopWindowAlwaysOnTop(alwaysOnTop),
    setDesktopWindowClickThrough: (enabled: boolean) => desktopApiMocks.setDesktopWindowClickThrough(enabled),
    startDesktopWindowDrag: () => desktopApiMocks.startDesktopWindowDrag(),
    syncDesktopChatWindowMiniLayout: () => desktopApiMocks.syncDesktopChatWindowMiniLayout(),
    toggleMaximizeDesktopWindow: () => desktopApiMocks.toggleMaximizeDesktopWindow(),
  };
});

const mioSprite: ChatStageSprite = {
  avatarType: "static",
  characterName: "Mio",
  id: "mio",
  label: "Mio",
  modelUrl: "",
  path: "http://127.0.0.1:8787/api/media?path=mio.png",
  slot: 0,
};

const aoiSprite: ChatStageSprite = {
  avatarType: "static",
  characterName: "Aoi",
  id: "aoi",
  label: "Aoi",
  modelUrl: "",
  path: "http://127.0.0.1:8787/api/media?path=aoi.png",
  slot: 1,
};

function renderMiniStage(overrides: Partial<ComponentProps<typeof MiniAvatarStage>> = {}) {
  const { inputValue: initialInputValue = "", onChangeInput, onSubmit, ...restOverrides } = overrides;
  function Wrapper() {
    const [value, setValue] = useState(initialInputValue);
    return (
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance={false}
          dialogCharacterName="Mio"
          dialogText="Hello from Mio!"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          notificationVisible={false}
          onAdvance={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onToggleScreenShare={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={["Earlier message"]}
          sprites={[mioSprite, aoiSprite]}
          standaloneDesktopWindow={false}
          status="idle"
          typing={false}
          userDisplayName="Player"
          {...restOverrides}
          inputValue={value}
          onChangeInput={(next) => {
            setValue(next);
            onChangeInput?.(next);
          }}
          onSubmit={async (textOverride) => {
            await onSubmit?.(textOverride);
            setValue("");
          }}
        />
      </I18nProvider>
    );
  }

  return render(<Wrapper />);
}

function mockJsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    json: () => Promise.resolve(body),
    ok,
    status: ok ? 200 : 400,
    statusText: ok ? "OK" : "Bad Request",
  } as Response);
}

describe("resolveMiniAvatarSpeaker", () => {
  it("selects only the current speaker sprite and preserves the previous speaker across user turns", () => {
    expect(
      resolveMiniAvatarSpeaker({
        dialogCharacterName: "Aoi",
        previousSpeakerName: "Mio",
        sprites: [mioSprite, aoiSprite],
        userDisplayName: "Player",
      }),
    ).toEqual({
      speakerName: "Aoi",
      sprite: aoiSprite,
    });

    expect(
      resolveMiniAvatarSpeaker({
        dialogCharacterName: "Player",
        previousSpeakerName: "Aoi",
        sprites: [mioSprite, aoiSprite],
        userDisplayName: "Player",
      }),
    ).toEqual({
      speakerName: "Aoi",
      sprite: aoiSprite,
    });

    expect(
      resolveMiniAvatarSpeaker({
        dialogCharacterName: "Player",
        previousSpeakerName: "Mio",
        sprites: [mioSprite, aoiSprite],
        thinkingCharacterName: "Aoi",
        userDisplayName: "Player",
      }),
    ).toEqual({
      speakerName: "Aoi",
      sprite: aoiSprite,
    });
  });

  it("falls back to speaker name when no sprite asset is present", () => {
    expect(
      resolveMiniAvatarSpeaker({
        dialogCharacterName: "Narrator",
        sprites: [],
        userDisplayName: "Player",
      }),
    ).toEqual({
      speakerName: "Narrator",
      sprite: undefined,
    });
  });
});

describe("MiniAvatarStage component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
    desktopApiMocks.isDesktopChatWindow.mockReturnValue(false);
    desktopApiMocks.isTauriDesktop.mockReturnValue(false);
    desktopApiMocks.getDesktopWindowCursorState.mockResolvedValue({ focused: true, inside: true, x: 100, y: 100 });
    desktopApiMocks.setDesktopChatWindowMiniMode.mockResolvedValue({ dockSide: "right" });
    desktopApiMocks.setDesktopWindowClickThrough.mockResolvedValue(undefined);
    desktopApiMocks.syncDesktopChatWindowMiniLayout.mockResolvedValue({ dockSide: "right" });
    desktopApiMocks.setDesktopWindowAlwaysOnTop.mockResolvedValue(undefined);
    desktopApiMocks.startDesktopWindowDrag.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
  });

  it("renders only the active speaker circular avatar and switches when another character speaks", () => {
    const { rerender } = render(
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance={false}
          dialogCharacterName="Mio"
          dialogText="Mio speaking"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          inputValue=""
          notificationVisible={false}
          onAdvance={vi.fn()}
          onChangeInput={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onSubmit={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={[]}
          sprites={[mioSprite, aoiSprite]}
          standaloneDesktopWindow={false}
          status="idle"
          typing={false}
          userDisplayName="Player"
        />
      </I18nProvider>,
    );

    const imagesBefore = document.querySelectorAll(".mini-avatar__core img");
    expect(imagesBefore).toHaveLength(1);
    expect(imagesBefore[0]).toHaveAttribute("src", mioSprite.path);

    rerender(
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance={false}
          dialogCharacterName="Aoi"
          dialogText="Aoi speaking now"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          inputValue=""
          notificationVisible={false}
          onAdvance={vi.fn()}
          onChangeInput={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onSubmit={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={[]}
          sprites={[mioSprite, aoiSprite]}
          standaloneDesktopWindow={false}
          status="idle"
          typing={false}
          userDisplayName="Player"
        />
      </I18nProvider>,
    );

    const imagesAfter = document.querySelectorAll(".mini-avatar__core img");
    expect(imagesAfter).toHaveLength(1);
    expect(imagesAfter[0]).toHaveAttribute("src", aoiSprite.path);
    expect(screen.getByText("Aoi speaking now")).toBeInTheDocument();
  });

  it("reveals radial controls on hover with grace delay, toggles ASR/plus menu, and keeps input expanded after send", async () => {
    vi.useFakeTimers();
    const onCommand = vi.fn();
    const onSubmit = vi.fn();
    const onPickAttachments = vi.fn();
    const onExitMiniMode = vi.fn();

    renderMiniStage({
      asrEnabled: true,
      asrRunning: true,
      onCommand,
      onExitMiniMode,
      onPickAttachments,
      onSubmit,
    });

    const hub = document.querySelector(".mini-avatar__hub")!;
    const controls = screen.getByRole("toolbar", { name: "Mini avatar controls" });

    expect(controls).toHaveAttribute("data-visible", "false");
    expect(hub).not.toHaveAttribute("data-chat-stage-hitbox");
    // Persistent mic badge stays visible even before hovering.
    expect(screen.getByRole("status", { name: "Voice listening active" })).toBeInTheDocument();

    fireEvent.pointerEnter(hub);
    expect(controls).toHaveAttribute("data-visible", "true");
    expect(hub).toHaveAttribute("data-chat-stage-hitbox", "true");

    fireEvent.click(screen.getByRole("button", { name: "Pause ASR" }));
    expect(onCommand).toHaveBeenCalledWith({ type: "pause-asr" });

    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    expect(screen.getByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "File" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Share Screen" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Image" }));
    expect(onPickAttachments).toHaveBeenCalledWith("image");
    // Picking an attachment automatically expands and pins the input bar.
    const input = screen.getByPlaceholderText("Enter dialogue") as HTMLInputElement;
    expect(input).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "Stay expanded after sending" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(screen.getByPlaceholderText("Enter dialogue")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Enter dialogue")).toHaveValue("");

    // Escape closes the pinned input bar.
    fireEvent.keyDown(screen.getByPlaceholderText("Enter dialogue"), { key: "Escape" });
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();

    // Pointer leave hides radial controls only after the hover grace period.
    fireEvent.pointerLeave(hub);
    expect(controls).toHaveAttribute("data-visible", "true");
    act(() => {
      vi.advanceTimersByTime(MINI_AVATAR_HOVER_HIDE_MS);
    });
    expect(controls).toHaveAttribute("data-visible", "false");

    // Double-clicking the circular avatar exits mini mode.
    fireEvent.doubleClick(document.querySelector(".mini-avatar__core")!);
    expect(onExitMiniMode).toHaveBeenCalledTimes(1);
  });

  it("handles single-bubble advance, idle auto-dismiss, and hover recall", () => {
    vi.useFakeTimers();
    const onAdvance = vi.fn();

    const { rerender } = render(
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance
          dialogCharacterName="Mio"
          dialogText="Click to advance"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          inputValue=""
          notificationVisible={false}
          onAdvance={onAdvance}
          onChangeInput={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onSubmit={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={[]}
          sprites={[mioSprite]}
          standaloneDesktopWindow={false}
          status="idle"
          typing={false}
          userDisplayName="Player"
        />
      </I18nProvider>,
    );

    const bubble = document.querySelector(".mini-avatar__bubble")!;
    expect(bubble).toHaveAttribute("data-visible", "true");
    fireEvent.click(bubble);
    expect(onAdvance).toHaveBeenCalledTimes(1);

    rerender(
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance={false}
          dialogCharacterName="Mio"
          dialogText="Idle line"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          inputValue=""
          notificationVisible={false}
          onAdvance={onAdvance}
          onChangeInput={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onSubmit={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={[]}
          sprites={[mioSprite]}
          standaloneDesktopWindow={false}
          status="idle"
          typing={false}
          userDisplayName="Player"
        />
      </I18nProvider>,
    );

    expect(bubble).toHaveAttribute("data-visible", "true");
    act(() => {
      vi.advanceTimersByTime(MINI_AVATAR_IDLE_BUBBLE_HIDE_MS);
    });
    expect(bubble).toHaveAttribute("data-visible", "false");

    // Hovering the Chat satellite previews the dismissed bubble.
    fireEvent.pointerEnter(document.querySelector(".mini-avatar__hub")!);
    fireEvent.pointerEnter(screen.getByRole("button", { name: "Show input bar" }));
    expect(bubble).toHaveAttribute("data-visible", "true");
  });

  it("switches ChatStagePage between normal stage and mini avatar mode via TopStageTools and syncs Tauri window mode", async () => {
    desktopApiMocks.isTauriDesktop.mockReturnValue(true);
    desktopApiMocks.setDesktopChatWindowMiniMode.mockResolvedValue({ dockSide: "left" });

    const stageSnapshot: ChatSnapshot = {
      backgroundPath: "http://127.0.0.1:8787/api/media?path=school.png",
      characterName: "Mio",
      dialogText: "Welcome back!",
      historyEntries: [],
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [mioSprite, aoiSprite],
      status: "idle",
      voiceLanguage: "ja",
    };

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const pathname = new URL(String(input)).pathname;
      if (pathname === "/api/chat/snapshot") {
        return mockJsonResponse(stageSnapshot);
      }
      if (pathname === "/api/chat/history") {
        return mockJsonResponse([]);
      }
      if (pathname === "/api/chat/close") {
        return mockJsonResponse(stageSnapshot);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    vi.stubGlobal("fetch", fetchMock);
    platformMocks.getPlatform.mockReturnValue(createHttpPlatform("http://127.0.0.1:8787"));

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/chat-stage"]}>
          <I18nProvider language="en">
            <ChatStagePage />
          </I18nProvider>
        </MemoryRouter>
      </ToastProvider>,
    );

    await screen.findByText("Welcome back!");
    const stage = document.querySelector(".chat-stage")!;
    expect(stage).toHaveAttribute("data-mini-avatar", "false");
    expect(stage).toHaveAttribute("data-background", "media");
    expect(desktopApiMocks.setDesktopChatWindowMiniMode).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Mini avatar mode" }));

    await waitFor(() => expect(stage).toHaveAttribute("data-mini-avatar", "true"));
    expect(stage).toHaveAttribute("data-background", "transparent");
    expect(stage).toHaveAttribute("data-click-through", "true");
    expect(document.querySelector(".sprite-layer")).toHaveAttribute("hidden");
    expect(document.querySelector(".dialog-stack")).toHaveAttribute("hidden");
    expect(document.querySelector(".top-stage-tools")).not.toBeInTheDocument();
    expect(document.querySelector("[data-chat-stage-audio-player]")).toBeInTheDocument();
    await waitFor(() => expect(desktopApiMocks.setDesktopChatWindowMiniMode).toHaveBeenCalledWith(true, true));
    await waitFor(() => expect(document.querySelector(".mini-avatar-stage")).toHaveAttribute("data-dock-side", "left"));

    fireEvent.click(screen.getByRole("button", { name: "Exit mini avatar mode" }));

    await waitFor(() => expect(stage).toHaveAttribute("data-mini-avatar", "false"));
    expect(stage).toHaveAttribute("data-background", "media");
    expect(desktopApiMocks.setDesktopChatWindowMiniMode).toHaveBeenCalledWith(false, true);
    expect(document.querySelector(".top-stage-tools")).toBeInTheDocument();
  });

  it("supports F8 hold-to-talk and live ASR preview directly inside mini avatar mode", async () => {
    const stageSnapshot: ChatSnapshot = {
      backgroundPath: "http://127.0.0.1:8787/api/media?path=school.png",
      characterName: "Mio",
      dialogText: "Hold F8 to talk!",
      historyEntries: [],
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [mioSprite],
      status: "idle",
      voiceLanguage: "ja",
    };

    let eventListener: ((event: ChatStageEvent) => void) | null = null;
    const sendChatCommand = vi.fn().mockResolvedValue(stageSnapshot);
    const basePlatform = createHttpPlatform("http://127.0.0.1:8787");
    platformMocks.getPlatform.mockReturnValue({
      ...basePlatform,
      chat: {
        ...basePlatform.chat,
        command: sendChatCommand,
        getHistory: vi.fn().mockResolvedValue([]),
        getSnapshot: vi.fn().mockResolvedValue(stageSnapshot),
        subscribeEvents: vi.fn((listener) => {
          eventListener = listener;
          return () => {
            eventListener = null;
          };
        }),
      },
    });

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/chat-stage"]}>
          <I18nProvider language="en">
            <ChatStagePage />
          </I18nProvider>
        </MemoryRouter>
      </ToastProvider>,
    );

    await screen.findByText("Hold F8 to talk!");
    fireEvent.click(screen.getByRole("button", { name: "Mini avatar mode" }));
    await waitFor(() => expect(document.querySelector(".chat-stage")).toHaveAttribute("data-mini-avatar", "true"));

    // Enable F8 hold-to-talk directly from the mini avatar '+' menu.
    fireEvent.pointerEnter(document.querySelector(".mini-avatar__hub")!);
    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Enable F8 hold to talk" }));

    // Input bar is initially unpinned / hidden.
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();

    // Hold F8 -> begins ASR hold, reveals live recognized text even while unpinned, and sends on release.
    fireEvent.keyDown(window, { code: "F8" });
    await waitFor(() => expect(sendChatCommand).toHaveBeenCalledWith({ type: "begin-asr-hold" }));

    act(() => {
      eventListener?.({ seq: 1, text: "Hello via F8", ts: 1, type: "asr.partial", v: 1 });
    });
    expect(screen.getByPlaceholderText("Enter dialogue")).toHaveValue("Hello via F8");
    expect(document.querySelector(".mini-avatar__ring")).toHaveAttribute("data-state", "listening");

    fireEvent.keyUp(window, { code: "F8" });
    await waitFor(() => expect(sendChatCommand).toHaveBeenCalledWith({ type: "finish-asr-hold" }));

    act(() => {
      eventListener?.({ seq: 2, text: "Hello via F8", ts: 2, type: "asr.final", v: 1 });
      eventListener?.({ enabled: false, loading: false, running: false, seq: 3, ts: 3, type: "asr.state", v: 1 });
    });
    expect(screen.queryByPlaceholderText("Enter dialogue")).not.toBeInTheDocument();
  });

  it("drives static sprite mouth-sync inside the circular mini avatar when TTS voice plays", async () => {
    const context = { clearRect: vi.fn(), drawImage: vi.fn(), setTransform: vi.fn() };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);

    class PatchImage {
      onload?: () => void;
      value = "";
      set src(value: string) {
        this.value = value;
        queueMicrotask(() => this.onload?.());
      }
    }
    vi.stubGlobal("Image", PatchImage);

    let pendingFrame: FrameRequestCallback | null = null;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      pendingFrame = callback;
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {
      pendingFrame = null;
    });

    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({
        correction: { gain: 1, offsetX: 0, offsetY: 0, rotation: 0, scale: 1 },
        duration: 1,
        fps: 24,
        height: 1200,
        mouths: { closed: "mio-closed.png", half: "mio-half.png", open: "mio-open.png" },
        patchBox: [320, 260, 80, 60],
        track: [{ matrix: [1, 0, 0, 1, 0, 0], time: 0 }],
        version: 1,
        width: 800,
      }),
      ok: true,
    });
    vi.stubGlobal("fetch", fetchMock);

    const mioWithMouth: ChatStageSprite = {
      ...mioSprite,
      mouthSync: "http://127.0.0.1:8787/api/media?path=data/sprite/mio/mouth.json",
    };

    renderMiniStage({
      dialogCharacterName: "Mio",
      sprites: [mioWithMouth],
      status: "speaking",
    });

    const baseImage = document.querySelector<HTMLImageElement>(".mini-avatar__core img")!;
    expect(baseImage).toHaveAttribute("src", mioWithMouth.path);
    expect(document.querySelector(".mini-avatar__core canvas.sprite-mouth-media__overlay")).toBeInTheDocument();

    Object.defineProperties(baseImage, { naturalHeight: { value: 1200 }, naturalWidth: { value: 800 } });
    fireEvent.load(baseImage);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://127.0.0.1:8787/api/characters/sprites/mouth/profile?path=data/sprite/mio/mouth.json",
      ),
    );
    await act(async () => {});

    const stepFrame = (time: number) => {
      const callback = pendingFrame;
      pendingFrame = null;
      act(() => callback?.(time));
    };

    stepFrame(100);
    expect(String(context.drawImage.mock.lastCall?.[0]?.value)).toContain("mio-closed.png");

    act(() => routeAvatarVoice("Mio", 0.85));
    stepFrame(200);
    expect(String(context.drawImage.mock.lastCall?.[0]?.value)).toContain("mio-open.png");

    act(() => routeAvatarVoice("Mio", 0));
    stepFrame(210);
    expect(String(context.drawImage.mock.lastCall?.[0]?.value)).toContain("mio-closed.png");
  });

  it("plays video sprites (.mp4/.webm), adapts landscape orientation, and supports expression transition clips", () => {
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});

    const mioVideoIdle: ChatStageSprite = {
      ...mioSprite,
      path: "http://127.0.0.1:8787/api/media?path=mio-idle.mp4",
    };
    const mioVideoSmile: ChatStageSprite = {
      ...mioSprite,
      path: "http://127.0.0.1:8787/api/media?path=mio-smile.mp4",
      transitions: [
        {
          fromUrl: "http://127.0.0.1:8787/api/media?path=mio-idle.mp4",
          url: "http://127.0.0.1:8787/api/media?path=mio-idle-to-smile.webm",
        },
      ],
    };

    const { rerender } = render(
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance={false}
          dialogCharacterName="Mio"
          dialogText="Video sprite idle"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          inputValue=""
          notificationVisible={false}
          onAdvance={vi.fn()}
          onChangeInput={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onSubmit={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={[]}
          sprites={[mioVideoIdle]}
          standaloneDesktopWindow={false}
          status="speaking"
          typing={false}
          userDisplayName="Player"
        />
      </I18nProvider>,
    );

    const idleVideo = document.querySelector<HTMLVideoElement>(".mini-avatar__core video")!;
    expect(idleVideo).toBeInTheDocument();
    expect(idleVideo).toHaveAttribute("src", mioVideoIdle.path);
    expect(idleVideo).toHaveAttribute("autoplay");
    expect(idleVideo).toHaveAttribute("loop");
    expect(playSpy).toHaveBeenCalled();

    Object.defineProperties(idleVideo, { videoHeight: { value: 1080 }, videoWidth: { value: 1920 } });
    fireEvent.loadedMetadata(idleVideo);
    fireEvent.loadedData(idleVideo);

    const frame = document.querySelector(".mini-avatar__core .character-visual__static-frame")!;
    expect(frame).toHaveAttribute("data-orientation", "landscape");

    rerender(
      <I18nProvider language="en">
        <MiniAvatarStage
          asrEnabled={false}
          asrLoading={false}
          asrRunning={false}
          attachments={[]}
          batchEnabled={false}
          canAdvance={false}
          dialogCharacterName="Mio"
          dialogText="Video sprite smiling"
          dialogVisible
          dockSide="right"
          inputDisabled={false}
          inputValue=""
          notificationVisible={false}
          onAdvance={vi.fn()}
          onChangeInput={vi.fn()}
          onCommand={vi.fn()}
          onExitMiniMode={vi.fn()}
          onFlushBatch={vi.fn()}
          onInputActivity={vi.fn()}
          onPickAttachments={vi.fn()}
          onRemoveAttachment={vi.fn()}
          onResolveToolConfirmation={vi.fn()}
          onSelectOption={vi.fn()}
          onSubmit={vi.fn()}
          options={[]}
          optionsVisible={false}
          previousMessages={[]}
          sprites={[mioVideoSmile]}
          standaloneDesktopWindow={false}
          status="speaking"
          typing={false}
          userDisplayName="Player"
        />
      </I18nProvider>,
    );

    expect(
      document.querySelector('video[src="http://127.0.0.1:8787/api/media?path=mio-idle-to-smile.webm"]'),
    ).toBeInTheDocument();
  });

  it("mounts model avatars (Live2D/MMD) even when sprite.path carries a state JSON URL", async () => {
    const apply = vi.fn().mockResolvedValue(undefined);
    const setAttention = vi.fn();
    registerAvatarFormat({
      capabilities: { blink: true, motion: true, mouth: true, sampling: "none" },
      id: "mini-test-l2d",
      label: "Mini Test L2D",
      load: async () => ({
        Editor: () => null,
        create: async () => ({
          apply,
          capabilities: { blink: true, motion: true, mouth: true, sampling: "none" },
          controls: {},
          dispose: vi.fn(),
          readState: () => ({}),
          resize: vi.fn(),
          setAttention,
          setMouthOpen: vi.fn(),
        }),
      }),
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => ({ expression: "happy" }), ok: true }));

    const modelSprite: ChatStageSprite = {
      avatarType: "mini-test-l2d",
      characterName: "Mio",
      id: "mio-l2d",
      label: "Mio",
      modelUrl: "http://127.0.0.1:8787/api/media?path=mio.model3.json",
      path: "http://127.0.0.1:8787/api/media?path=mio-state.json",
      slot: 0,
    };

    renderMiniStage({
      dialogCharacterName: "Mio",
      sprites: [modelSprite],
      status: "speaking",
    });

    expect(screen.getByTestId("model-container")).toBeInTheDocument();
    expect(document.querySelector(".mini-avatar__core img")).toBeNull();
    await waitFor(() => expect(apply).toHaveBeenCalledWith({ expression: "happy" }, "play", expect.any(AbortSignal)));
    expect(setAttention).toHaveBeenLastCalledWith("responding");
  });

  it("handles pointer dragging in web and desktop modes, bubble dismiss/restore, options, tool confirmations, attachments, and fallbacks", async () => {
    const onAdvance = vi.fn();
    const onAutoPlayChange = vi.fn();
    const onDesktopDragEnd = vi.fn();
    const onDropFiles = vi.fn();
    const onFlushBatch = vi.fn();
    const onInputActivity = vi.fn();
    const onPickAttachments = vi.fn();
    const onRemoveAttachment = vi.fn();
    const onResolveToolConfirmation = vi.fn();
    const onSelectOption = vi.fn();
    const onSubmit = vi.fn();
    const onToggleScreenShare = vi.fn();

    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1000 });

    const { unmount } = renderMiniStage({
      attachments: [{ kind: "image", name: "photo.png", path: "/tmp/photo.png" }],
      autoPlay: false,
      batchEnabled: true,
      onAdvance,
      onAutoPlayChange,
      onDropFiles,
      onFlushBatch,
      onInputActivity,
      onPickAttachments,
      onRemoveAttachment,
      onResolveToolConfirmation,
      onSelectOption,
      onSubmit,
      onToggleScreenShare,
      options: [
        "First choice",
        {
          enabled: false,
          expectedNodeId: "node-1",
          expectedRevision: 1,
          id: "opt-2",
          label: "Disabled choice",
          source: "story",
        },
      ],
      optionsVisible: true,
      runtimeFramingForSprite: () => ({ heightRatio: 0.6, verticalPosition: 0.1 }),
    });

    // Options list renders inside the single bubble and triggers selection.
    fireEvent.click(screen.getByRole("button", { name: "First choice" }));
    expect(onSelectOption).toHaveBeenCalledWith("First choice");
    expect(screen.getByRole("button", { name: "Disabled choice" })).toBeDisabled();

    // Attachment automatically pinned the input bar; test chip removal, ArrowUp history recall, composition, and Ctrl+Enter flush.
    fireEvent.click(screen.getByRole("button", { name: /photo\.png/i }));
    expect(onRemoveAttachment).toHaveBeenCalledWith({ kind: "image", name: "photo.png", path: "/tmp/photo.png" });

    const input = screen.getByPlaceholderText("Enter dialogue");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input).toHaveValue("Earlier message");
    expect(onInputActivity).toHaveBeenCalledWith({ composing: false, hasText: true });

    fireEvent.compositionStart(input);
    fireEvent.compositionEnd(input);
    await act(async () => {
      fireEvent.keyDown(input, { ctrlKey: true, key: "Enter" });
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onFlushBatch).toHaveBeenCalledTimes(1);

    // Drag & drop files onto hub.
    const hub = document.querySelector(".mini-avatar__hub")!;
    const droppedFile = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.dragOver(hub, { dataTransfer: { files: [droppedFile], types: ["Files"] } });
    expect(document.querySelector(".mini-avatar-stage")).toHaveAttribute("data-drag-active", "true");
    fireEvent.dragLeave(hub);
    expect(document.querySelector(".mini-avatar-stage")).toHaveAttribute("data-drag-active", "false");
    fireEvent.drop(hub, { dataTransfer: { files: [droppedFile], types: ["Files"] } });
    expect(onDropFiles).toHaveBeenCalledWith([droppedFile]);

    // Plus menu actions: File, Share Screen, AutoPlay.
    fireEvent.pointerEnter(hub);
    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    fireEvent.click(screen.getByRole("button", { name: "File" }));
    expect(onPickAttachments).toHaveBeenCalledWith("file");

    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Share Screen" }));
    expect(onToggleScreenShare).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "More input actions" }));
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Auto-play" }));
    expect(onAutoPlayChange).toHaveBeenCalledWith(true);

    // Web mode pointer drag flips dock side to left and suppresses post-drag click.
    const avatarButton = document.querySelector<HTMLButtonElement>(".mini-avatar__core")!;
    fireEvent(
      avatarButton,
      Object.assign(new MouseEvent("pointerdown", { bubbles: true, button: 0, clientX: 800, clientY: 200 }), {
        pointerId: 1,
      }),
    );
    fireEvent(
      avatarButton,
      Object.assign(new MouseEvent("pointermove", { bubbles: true, clientX: 200, clientY: 180 }), { pointerId: 1 }),
    );
    fireEvent(
      avatarButton,
      Object.assign(new MouseEvent("pointerup", { bubbles: true, clientX: 200, clientY: 180 }), { pointerId: 1 }),
    );
    expect(document.querySelector(".mini-avatar-stage")).toHaveAttribute("data-dock-side", "left");
    fireEvent.click(avatarButton);
    expect(onAdvance).not.toHaveBeenCalled();

    // Image load error falls back to speaker initial cleanly.
    fireEvent.error(document.querySelector(".mini-avatar__core img")!);
    expect(document.querySelector(".mini-avatar__initial")).toHaveTextContent("M");

    unmount();

    // Tool confirmation, desktop window drag, and bubble dismiss/restore.
    renderMiniStage({
      dialogCharacterName: "",
      dialogText: "Dismissable line",
      onDesktopDragEnd,
      onResolveToolConfirmation,
      sprites: [],
      standaloneDesktopWindow: true,
      toolConfirmation: { confirmationId: "tc-1", detail: "Write file", risk: "medium", toolName: "save_note" },
    });

    fireEvent.click(screen.getByRole("button", { name: /save_note/i }));
    expect(onResolveToolConfirmation).toHaveBeenCalledWith("confirm");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onResolveToolConfirmation).toHaveBeenCalledWith("cancel");

    const desktopAvatar = document.querySelector<HTMLButtonElement>(".mini-avatar__core")!;
    fireEvent(
      desktopAvatar,
      Object.assign(new MouseEvent("pointerdown", { bubbles: true, button: 0, clientX: 50, clientY: 50 }), {
        pointerId: 2,
      }),
    );
    fireEvent(
      desktopAvatar,
      Object.assign(new MouseEvent("pointermove", { bubbles: true, clientX: 80, clientY: 70 }), { pointerId: 2 }),
    );
    fireEvent(
      desktopAvatar,
      Object.assign(new MouseEvent("pointerup", { bubbles: true, clientX: 80, clientY: 70 }), { pointerId: 2 }),
    );
    await waitFor(() => expect(desktopApiMocks.startDesktopWindowDrag).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onDesktopDragEnd).toHaveBeenCalledTimes(1));

    cleanup();
    renderMiniStage({
      dialogCharacterName: "Mio",
      dialogText: "Line that can be dismissed manually",
    });
    const bubble = document.querySelector(".mini-avatar__bubble")!;
    expect(bubble).toHaveAttribute("data-visible", "true");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss bubble" }));
    expect(bubble).toHaveAttribute("data-visible", "false");
    fireEvent.click(document.querySelector(".mini-avatar__core")!);
    expect(bubble).toHaveAttribute("data-visible", "true");
  });
});
