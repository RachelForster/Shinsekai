import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ChatCommand, ChatSnapshot } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  getChatSnapshot: vi.fn(),
  getChatTheme: vi.fn(),
  sendChatCommand: vi.fn(),
  subscribeChat: vi.fn(),
};

vi.mock("../../../entities/chat/repository", () => ({
  getChatSnapshot: () => mocks.getChatSnapshot(),
  getChatTheme: () => mocks.getChatTheme(),
  sendChatCommand: (command: ChatCommand) => mocks.sendChatCommand(command),
  subscribeChat: (listener: (snapshot: ChatSnapshot) => void) => mocks.subscribeChat(listener),
}));

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

function snapshot(overrides: Partial<ChatSnapshot> = {}): ChatSnapshot {
  return {
    backgroundPath: "asset://school.png",
    characterName: "Mio",
    dialogText: "Ready",
    historyPath: "D:/history/session.json",
    inputDraft: "",
    numericInfo: "idle / 2",
    options: ["Take the shortcut"],
    sprites: [{ id: "mio", label: "Mio", path: "asset://mio.png" }],
    status: "idle",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <ToastProvider>
      <I18nProvider language="en">
        <ChatStagePage />
      </I18nProvider>
    </ToastProvider>,
  );
}

describe("ChatStagePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getChatTheme.mockResolvedValue({});
    mocks.getChatSnapshot.mockResolvedValue(snapshot());
    mocks.sendChatCommand.mockImplementation(async (command: ChatCommand) =>
      snapshot({
        dialogText: command.type,
        inputDraft: "",
        options: [],
      }),
    );
    mocks.subscribeChat.mockReturnValue(vi.fn());
  });

  it("sends option selections and typed dialogue through chat commands", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Take the shortcut" }));
    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "Take the shortcut",
        type: "submit-option",
      }),
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  hello  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(mocks.sendChatCommand).toHaveBeenCalledWith({
        payload: "hello",
        type: "send-message",
      }),
    );
  });

  it("requires confirmation before clearing chat history", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Clear history" }));
    expect(mocks.sendChatCommand).not.toHaveBeenCalledWith({ type: "clear-history" });

    const dialog = screen.getByRole("dialog", { name: "Clear history" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear" }));

    await waitFor(() => expect(mocks.sendChatCommand).toHaveBeenCalledWith({ type: "clear-history" }));
  });
});
