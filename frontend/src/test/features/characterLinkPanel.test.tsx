import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../shared/i18n";

const method = vi.hoisted(() => vi.fn());
vi.mock("../../shared/platform/platform", () => ({ getPlatform: () => ({ characters: { linkDoki: method } }) }));
vi.mock("../../shared/ui", async () => ({
  ...(await import("../../shared/ui/Button")),
  Dialog: (await import("../../shared/ui/Dialog")).Dialog,
  Select: (props: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...props} />,
}));
import { CharacterLinkPanel } from "../../features/character-editor/CharacterLinkPanel";
import type { Character } from "../../entities/config/types";

describe("explicit role linking", () => {
  beforeEach(() => vi.resetAllMocks());
  it("suggests a matching name without binding until confirmation, and permits manual choice", async () => {
    method.mockImplementation(async ({ action }) =>
      action === "doki-list"
        ? {
            characters: [
              { id: "other", name: "Other", role: "character", linked: false },
              { id: "match", name: "A", role: "character", linked: false },
            ],
          }
        : action === "bind"
          ? { link: { id: "link", doki_name: "Other", role: "character" } }
          : { link: null },
    );
    render(
      <I18nProvider language="zh_CN">
        <CharacterLinkPanel character={{ id: "shin-a", name: "A" } as Character} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "链接 Doki 角色" }));
    const select = await screen.findByLabelText("选择对应角色（同名优先，可手动选择）");
    expect(select).toHaveValue("character:match");
    expect(method.mock.calls.some(([value]) => value.action === "bind")).toBe(false);
    fireEvent.change(select, { target: { value: "character:other" } });
    fireEvent.click(screen.getByRole("button", { name: "确认链接" }));
    await waitFor(() =>
      expect(method).toHaveBeenCalledWith({
        action: "bind",
        characterId: "shin-a",
        dokiId: "other",
        role: "character",
      }),
    );
    expect(await screen.findByText("已链接：Other")).toBeVisible();
  });
  it("keeps player profile linkage distinct and unlinks without changing character settings", async () => {
    method.mockImplementation(async ({ action }) =>
      action === "state" ? { link: { id: "link", doki_name: "水岛神羽", role: "player" } } : { link: null },
    );
    const character = { id: "oc", name: "水岛神羽", character_setting: "keep" } as Character;
    render(
      <I18nProvider language="zh_CN">
        <CharacterLinkPanel character={character} />
      </I18nProvider>,
    );
    await screen.findByText(/我的资料／玩家角色/);
    fireEvent.click(screen.getByRole("button", { name: "解除链接" }));
    await waitFor(() =>
      expect(method).toHaveBeenCalledWith({ action: "unlink", characterId: "oc", dokiId: undefined, role: undefined }),
    );
    expect(character.character_setting).toBe("keep");
  });
  it("opens compact link management in a body portal outside a clipped toolbar", async () => {
    method.mockResolvedValue({ link: null, characters: [] });
    const { container } = render(
      <I18nProvider language="zh_CN">
        <div style={{ overflow: "hidden", height: 40 }}>
          <CharacterLinkPanel compact character={{ id: "native", name: "A" } as Character} />
        </div>
      </I18nProvider>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "链接 Doki 角色" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeVisible();
    expect(container.contains(dialog)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
