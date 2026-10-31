import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Character } from "../../entities/config/types";
import { I18nProvider } from "../../shared/i18n";

const methods = vi.hoisted(() => ({ listDoki: vi.fn(), prepareExchange: vi.fn() }));
vi.mock("../../shared/platform/platform", () => ({ getPlatform: () => ({ characters: methods }) }));
vi.mock("../../shared/ui", async () => ({
  ...(await import("../../shared/ui/Button")),
  ...(await import("../../shared/ui/EmptyState")),
  Select: (props: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...props} />,
  PathPickerDialog: () => null,
}));

import { CharacterExchangePanel } from "../../features/character-editor/CharacterExchangePanel";

describe("cross-app character import preview", () => {
  beforeEach(() => vi.resetAllMocks());
  it("reading the Doki list does not import; cancellation does not commit a character", async () => {
    methods.listDoki.mockResolvedValue({ characters: [{ id: "a", name: "A", persona: "public" }] });
    const prepared = vi.fn();
    render(
      <I18nProvider language="zh_CN">
        <CharacterExchangePanel characters={[]} selectedName="" onPrepared={prepared} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByText("从 Doki 选择角色导入"));
    await screen.findByText("public");
    expect(methods.prepareExchange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("取消"));
    expect(prepared).not.toHaveBeenCalled();
  });
  it("updates only the explicitly selected target and returns a draft to the page", async () => {
    methods.listDoki.mockResolvedValue({ characters: [{ id: "a", name: "A", persona: "public" }] });
    const character = { name: "Existing", emotion_resources: [{ tag: "愤怒", voice_path: "angry.wav" }] } as Character;
    methods.prepareExchange.mockResolvedValue({ character, originalName: "Existing" });
    const prepared = vi.fn();
    render(
      <I18nProvider language="zh_CN">
        <CharacterExchangePanel
          characters={[{ name: "Existing" } as Character]}
          selectedName="Existing"
          onPrepared={prepared}
        />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByText("从 Doki 选择角色导入"));
    await screen.findByText("public");
    fireEvent.change(screen.getByLabelText("保存方式"), { target: { value: "Existing" } });
    fireEvent.click(screen.getByText("载入角色资料"));
    await waitFor(() => expect(prepared).toHaveBeenCalledWith(character, "Existing"));
    expect(methods.prepareExchange).toHaveBeenCalledWith({ dokiId: "a", targetName: "Existing" });
  });
  it("shows the native loading state, prevents duplicate actions and recovers after an error", async () => {
    let reject!: (error: Error) => void;
    methods.listDoki.mockReturnValue(
      new Promise((_resolve, fail) => {
        reject = fail;
      }),
    );
    render(
      <I18nProvider language="zh_CN">
        <CharacterExchangePanel characters={[]} selectedName="" onPrepared={vi.fn()} />
      </I18nProvider>,
    );
    const button = screen.getByRole("button", { name: "从 Doki 选择角色导入" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    expect(document.querySelector(".character-exchange")).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector(".button__spinner")).not.toBeNull();
    reject(new Error("测试连接不可用"));
    expect(await screen.findByRole("alert")).toHaveTextContent("测试连接不可用");
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
