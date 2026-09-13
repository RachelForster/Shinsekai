import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { TemplateWorkspacePage } from "../../../features/template-workspace/TemplateWorkspacePage";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../features/template-editor/TemplateEditorPage", () => ({
  TemplateEditorPage: () => <input aria-label="正常模式草稿" defaultValue="正常草稿" />,
}));
vi.mock("../../../features/template-workspace/ConversationLibrary", () => ({
  ConversationLibrary: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>Open new chat</button>,
}));
vi.mock("../../../features/story-generator/StoryGeneratorPage", () => ({
  StoryGeneratorPage: () => <input aria-label="剧本模式草稿" defaultValue="剧本草稿" />,
}));

describe("creation mode tabs", () => {
  it("defaults to recent chats and opens creation only on request", async () => {
    render(
      <MemoryRouter>
        <I18nProvider language="en">
          <TemplateWorkspacePage />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getByRole("tab", { name: "Recent chats" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("textbox", { name: "正常模式草稿" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open new chat" }));
    expect(await screen.findByRole("textbox", { name: "正常模式草稿" })).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "正常模式草稿" }), { target: { value: "Draft" } });
    fireEvent.click(screen.getByRole("tab", { name: "Recent chats" }));
    fireEvent.click(screen.getByRole("tab", { name: "New chat" }));
    expect(screen.getByRole("textbox", { name: "正常模式草稿" })).toHaveValue("Draft");
  });
  it("uses translated tab labels without changing mode navigation", async () => {
    render(
      <MemoryRouter initialEntries={["/settings/templates?tab=new"]}>
        <I18nProvider language="en">
          <TemplateWorkspacePage />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getByRole("tablist", { name: "Creation mode" })).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Story mode" }));
    expect(await screen.findByRole("textbox", { name: "剧本模式草稿" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Normal mode" })).toHaveAttribute("aria-selected", "false");
  });
  it("keeps both drafts when switching modes and supports keyboard navigation", async () => {
    render(
      <MemoryRouter initialEntries={["/settings/templates?tab=new"]}>
        <I18nProvider language="zh_CN">
          <TemplateWorkspacePage />
        </I18nProvider>
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "正常模式草稿" }), { target: { value: "未保存" } });
    expect(screen.getByText("普通聊天")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "剧本模式" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "剧本模式草稿" }), {
      target: { value: "生成中的故事" },
    });
    expect(screen.getByText("剧本聊天")).toBeVisible();
    expect(screen.queryByText("普通聊天")).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: "剧本模式" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "正常模式" })).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "正常模式草稿" })).toHaveValue("未保存");
    fireEvent.keyDown(screen.getByRole("tab", { name: "正常模式" }), { key: "End" });
    expect(screen.getByRole("textbox", { name: "剧本模式草稿" })).toHaveValue("生成中的故事");
  });

  it("opens story mode from a deep link", async () => {
    render(
      <MemoryRouter initialEntries={["/settings/templates?mode=story"]}>
        <I18nProvider language="zh_CN">
          <TemplateWorkspacePage />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("textbox", { name: "剧本模式草稿" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "剧本模式" })).toHaveAttribute("aria-selected", "true");
  });
});
