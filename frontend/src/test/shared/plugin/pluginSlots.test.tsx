import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { normalizePluginContributions, PluginSlot } from "../../../shared/plugin/PluginSlot";
import type { PluginUIContribution } from "../../../shared/plugin/PluginSlot";
import { ToastProvider } from "../../../shared/ui";

const repository = vi.hoisted(() => ({
  list: vi.fn(),
  run: vi.fn(),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  listPluginSlotContributions: repository.list,
  pluginSlotContributionsQueryKey: ["plugins", "slot-contributions"],
  runPluginSlotContribution: repository.run,
}));

const validContribution: PluginUIContribution = {
  id: "demo.output",
  permissions: ["chat:read"],
  render: ({ title }) => <span>{title}</span>,
  slot: "chat-output",
  title: "Demo Output",
};

describe("plugin slot registry", () => {
  beforeEach(() => {
    repository.list.mockReset().mockResolvedValue([]);
    repository.run.mockReset().mockResolvedValue({
      id: "demo.safe-action",
      kind: "success",
      message: "Action complete",
      pluginId: "demo.plugin",
    });
  });
  it("keeps only declared, unique plugin contributions", () => {
    const normalized = normalizePluginContributions([
      { ...validContribution, id: " demo.output ", title: " Demo Output " },
      { ...validContribution, id: "demo.output", title: "Duplicate" },
      { ...validContribution, id: "", title: "Missing ID" },
      { ...validContribution, id: "missing.title", title: "" },
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0]).toMatchObject({
      id: "demo.output",
      permissions: ["chat:read"],
      title: "Demo Output",
    });
  });

  it("renders only contributions for the requested fixed slot", () => {
    render(
      <PluginSlot
        contributions={[
          validContribution,
          {
            ...validContribution,
            id: "demo.toolbar",
            render: () => <span>Toolbar</span>,
            slot: "chat-toolbar",
            title: "Toolbar",
          },
        ]}
        slot="chat-output"
      />,
    );

    expect(screen.getByText("Demo Output")).toBeInTheDocument();
    expect(screen.queryByText("Toolbar")).not.toBeInTheDocument();
    expect(screen.getByText("Demo Output").parentElement).toHaveAttribute("data-plugin-slot", "chat-output");
  });

  it("accepts dialog action contributions as a dedicated chat UI slot", () => {
    render(
      <PluginSlot
        contributions={[
          {
            ...validContribution,
            id: "demo.dialog-actions",
            render: () => <button type="button">Custom Dialog Action</button>,
            slot: "chat-dialog-actions",
            title: "Dialog Action",
          },
        ]}
        slot="chat-dialog-actions"
      />,
    );

    expect(screen.getByRole("button", { name: "Custom Dialog Action" }).parentElement).toHaveAttribute(
      "data-plugin-slot",
      "chat-dialog-actions",
    );
  });

  it("fetches JSON contributions and renders them through host-owned components", async () => {
    repository.list.mockResolvedValue([
      {
        actionLabel: "Run safe action",
        actionType: "callback",
        actionable: true,
        description: "No plugin JavaScript is rendered.",
        icon: "sparkles",
        id: "demo.safe-action",
        order: 10,
        pageId: "",
        pluginId: "demo.plugin",
        pluginVersion: "1.0.0",
        presentation: "button",
        slot: "chat-output",
        title: "Safe contribution",
        variant: "primary",
      },
    ]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <PluginSlot slot="chat-output" />
        </ToastProvider>
      </QueryClientProvider>,
    );

    const action = await screen.findByRole("button", { name: "Run safe action" });
    expect(action.closest("[data-plugin-contribution]"))?.toHaveAttribute("data-plugin-id", "demo.plugin");
    fireEvent.click(action);

    await waitFor(() => expect(repository.run).toHaveBeenCalledWith("demo.plugin", "demo.safe-action"));
    expect(await screen.findByText("Action complete")).toBeInTheDocument();
  });

  it("renders a host-owned phone icon that opens a declared plugin page", async () => {
    repository.list.mockResolvedValue([
      {
        actionLabel: "Phone",
        actionType: "open-plugin-page",
        actionable: true,
        description: "Open the phone panel",
        icon: "smartphone",
        id: "demo.phone",
        order: 30,
        pageId: "phone",
        pluginId: "demo.plugin",
        pluginVersion: "1.0.0",
        presentation: "icon-only",
        slot: "chat-top-toolbar",
        title: "Phone",
        variant: "ghost",
      },
    ]);
    const onOpenPluginPage = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <PluginSlot onOpenPluginPage={onOpenPluginPage} slot="chat-top-toolbar" />
        </ToastProvider>
      </QueryClientProvider>,
    );

    const phoneButton = await screen.findByRole("button", { name: "Phone" });
    expect(phoneButton).toHaveClass("top-stage-tools__button", "plugin-slot__icon-button");
    expect(phoneButton).not.toHaveTextContent("Phone");
    fireEvent.click(phoneButton);

    expect(onOpenPluginPage).toHaveBeenCalledWith({ pageId: "phone", pluginId: "demo.plugin" });
    expect(repository.run).not.toHaveBeenCalled();
  });
});
