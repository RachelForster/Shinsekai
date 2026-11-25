import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ChatCommand, ChatSnapshot } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  browseFiles: vi.fn(),
  closeChat: vi.fn(),
  getAppConfig: vi.fn(),
  getChatHistory: vi.fn(),
  getChatHistoryVoice: vi.fn(),
  getChatReplay: vi.fn(),
  getChatSnapshot: vi.fn(),
  getChatTheme: vi.fn(),
  sendChatCommand: vi.fn(),
  subscribeChatEvents: vi.fn(),
  uploadChatAttachments: vi.fn(),
};

vi.mock("../../../entities/chat/repository", () => ({
  closeChat: () => mocks.closeChat(),
  getChatHistory: () => mocks.getChatHistory(),
  getChatHistoryVoice: (voiceId: string) => mocks.getChatHistoryVoice(voiceId),
  getChatReplay: (id: string) => mocks.getChatReplay(id),
  getChatSnapshot: () => mocks.getChatSnapshot(),
  getChatTheme: () => mocks.getChatTheme(),
  sendChatCommand: (command: ChatCommand) => mocks.sendChatCommand(command),
  subscribeChatEvents: (listener: (event: unknown) => void) => mocks.subscribeChatEvents(listener),
  uploadChatAttachments: (files: File[]) => mocks.uploadChatAttachments(files),
}));

vi.mock("../../../entities/config/repository", () => ({
  getAppConfig: () => mocks.getAppConfig(),
}));

vi.mock("../../../entities/files/repository", () => ({
  browseFiles: (options?: { path?: string; showHidden?: boolean }) => mocks.browseFiles(options),
  fileUrl: (path: string) => path,
}));

vi.mock("../../../features/chat-stage/theme/ChatThemeProvider", () => ({
  useOptionalChatTheme: () => null,
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  closeChatSurface: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/desktop/desktopApi")>();
  return {
    ...actual,
    isTauriDesktop: () => false,
  };
});

function baseSnapshot(overrides: Partial<ChatSnapshot> = {}): ChatSnapshot {
  return {
    backgroundPath: "asset://school.png",
    characterName: "Mio",
    dialogText: "Line one",
    historyEntries: [],
    historyPath: "D:/history/session.json",
    inputDraft: "",
    numericInfo: "idle / 1",
    options: [],
    sprites: [{ avatarType: "static", id: "mio", label: "Mio", modelUrl: "", path: "asset://mio.png" }],
    status: "idle",
    userDisplayName: "Aoi",
    voiceLanguage: "ja",
    ...overrides,
  };
}

function renderStage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/"]}>
        <I18nProvider language="en">
          <ChatStagePage />
        </I18nProvider>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("ChatStagePage behavior command wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
    mocks.closeChat.mockResolvedValue(baseSnapshot());
    mocks.getAppConfig.mockResolvedValue({ api_config: {} });
    mocks.browseFiles.mockResolvedValue({ cwd: "", entries: [], roots: [] });
    mocks.getChatTheme.mockResolvedValue({});
    mocks.getChatHistory.mockResolvedValue([]);
    mocks.getChatHistoryVoice.mockResolvedValue([]);
    mocks.getChatReplay.mockReturnValue(new Promise(() => {}));
    mocks.sendChatCommand.mockResolvedValue(baseSnapshot());
    mocks.uploadChatAttachments.mockResolvedValue({ attachments: [] });
    mocks.subscribeChatEvents.mockReturnValue(vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("dispatches versioned behavior-command when clicking a behavior option and hides input", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      baseSnapshot({
        behavior: {
          behaviorId: "galgame_tutor",
          stateVersion: 5,
          stagePolicy: {
            hideInputLayer: false,
            playbackEndAction: "show_options",
            allowFreeTextInterject: false,
            allowUnboundSpeakers: true,
          },
          options: [{ id: "choice-1", label: "Answer B", action: "answer", payload: { choice: "B" } }],
        },
      }),
    );
    const { container } = renderStage();

    const button = await screen.findByRole("button", { name: "Answer B" });
    expect(container.querySelector(".input-layer")).toBeNull();
    fireEvent.click(button);

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledTimes(1));
    const cmd = mocks.sendChatCommand.mock.calls[0][0] as ChatCommand;
    expect(cmd.type).toBe("behavior-command");
    const payload = cmd.payload as Record<string, unknown>;
    expect(typeof payload.commandId).toBe("string");
    expect(String(payload.commandId).length).toBeGreaterThan(0);
    expect(payload.action).toBe("answer");
    expect(payload.expectedStateVersion).toBe(5);
    expect(payload.payload).toEqual({ choice: "B", optionId: "choice-1" });
  });

  it("dispatches versioned behavior-command on dialog advance for auto_advance", async () => {
    mocks.getChatSnapshot.mockResolvedValue(
      baseSnapshot({
        behavior: {
          behaviorId: "novel_theater",
          stateVersion: 11,
          stagePolicy: {
            hideInputLayer: true,
            playbackEndAction: "auto_advance",
            allowFreeTextInterject: false,
            allowUnboundSpeakers: true,
          },
        },
      }),
    );
    const { container } = renderStage();

    await screen.findByText("Line one");
    const dialogLayer = container.querySelector(".dialog-layer") as HTMLElement;
    fireEvent.click(dialogLayer);

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledTimes(1));
    const cmd = mocks.sendChatCommand.mock.calls[0][0] as ChatCommand;
    expect(cmd.type).toBe("behavior-command");
    const payload = cmd.payload as Record<string, unknown>;
    expect(typeof payload.commandId).toBe("string");
    expect(payload.action).toBe("advance");
    expect(payload.expectedStateVersion).toBe(11);
    expect(payload.payload).toEqual({ trigger: "playback_end" });
  });
});
