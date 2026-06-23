import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { PluginPublisherDialog } from "../../../features/plugin-manager/PluginPublisherDialog";
import { I18nProvider } from "../../../shared/i18n";
import { ToastProvider } from "../../../shared/ui";

const fileMocks = vi.hoisted(() => ({
  browseFiles: vi.fn(),
  openExternal: vi.fn(),
}));

const pluginMocks = vi.hoisted(() => ({
  buildPluginSubmissionIssueUrl: vi.fn(),
  copyPluginSubmissionJson: vi.fn(),
  scanLocalPlugin: vi.fn(),
  validatePluginSubmission: vi.fn(),
}));

vi.mock("../../../entities/files/repository", () => ({
  browseFiles: (...args: unknown[]) => fileMocks.browseFiles(...args),
  openExternal: (url: string) => fileMocks.openExternal(url),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  buildPluginSubmissionIssueUrl: (input: unknown) => pluginMocks.buildPluginSubmissionIssueUrl(input),
  copyPluginSubmissionJson: (input: unknown) => pluginMocks.copyPluginSubmissionJson(input),
  scanLocalPlugin: (path: string) => pluginMocks.scanLocalPlugin(path),
  validatePluginSubmission: (input: unknown) => pluginMocks.validatePluginSubmission(input),
}));

vi.mock("../../../shared/ui", async () => {
  const actual = await vi.importActual<typeof import("../../../shared/ui")>("../../../shared/ui");
  return {
    ...actual,
    FilePicker: ({
      onPathChange,
      pickLabel,
      value,
    }: {
      onPathChange?: (path: string) => void;
      pickLabel?: string;
      value?: string;
    }) => (
      <input
        aria-label={pickLabel}
        onChange={(event) => onPathChange?.(event.target.value)}
        value={value ?? ""}
      />
    ),
  };
});

function renderDialog(onClose = vi.fn()) {
  render(
    <ToastProvider>
      <I18nProvider language="en">
        <PluginPublisherDialog onClose={onClose} open />
      </I18nProvider>
    </ToastProvider>,
  );
  return { onClose };
}

function fillValidForm() {
  fireEvent.change(screen.getByPlaceholderText("Shinsekai Plugin"), {
    target: { value: "Vision Helper" },
  });
  fireEvent.change(screen.getByPlaceholderText("Shinsekai Contributors"), {
    target: { value: "Alice" },
  });
  fireEvent.change(screen.getByPlaceholderText("https://github.com/shinsekai/plugin-example"), {
    target: { value: "https://github.com/alice/vision-helper.git" },
  });
  fireEvent.change(screen.getByPlaceholderText(">=0.2.0"), {
    target: { value: ">=0.3.0" },
  });
  fireEvent.change(screen.getByPlaceholderText("Example plugin for Shinsekai, describing core capabilities and use cases."), {
    target: { value: "Adds a vision helper tool." },
  });
  fireEvent.change(screen.getByPlaceholderText("shinsekai, example"), {
    target: { value: "vision, helper tts" },
  });
  fireEvent.change(screen.getByPlaceholderText("Your Bilibili, GitHub profile, or personal site"), {
    target: { value: "https://github.com/alice" },
  });
}

describe("PluginPublisherDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fileMocks.openExternal.mockResolvedValue(undefined);
    pluginMocks.buildPluginSubmissionIssueUrl.mockResolvedValue({
      issueUrl: "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new?template=PLUGIN_PUBLISH.yml",
      json: "{\"display_name\":\"Vision Helper\"}",
    });
    pluginMocks.copyPluginSubmissionJson.mockResolvedValue({
      clipboardText: "{\"display_name\":\"Vision Helper\"}",
      json: "{\"display_name\":\"Vision Helper\"}",
    });
    pluginMocks.scanLocalPlugin.mockResolvedValue({
      author: "Scanned Author",
      desc: "Scanned description",
      display_name: "Scanned Plugin",
      lowest_shinsekai_version: ">=0.4.0",
      repo: "https://github.com/scanned/plugin",
      social_link: "https://example.test/scanned",
      tags: ["scan", "metadata"],
      warnings: ["requirements.txt was not found"],
    });
    pluginMocks.validatePluginSubmission.mockResolvedValue({
      errors: [],
      json: "{\"ok\":true}",
      ok: true,
    });
  });

  it("requires a local path before scanning and then prefills metadata with warnings", async () => {
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Read metadata" }));
    expect(await screen.findByText("Choose a local source path.")).toBeInTheDocument();

    fireEvent.change(screen.getAllByLabelText("Optional: local source path")[0], { target: { value: "/plugins/demo" } });
    fireEvent.click(screen.getByRole("button", { name: "Read metadata" }));

    await waitFor(() => expect(pluginMocks.scanLocalPlugin).toHaveBeenCalledWith("/plugins/demo"));
    expect(screen.getByDisplayValue("Scanned Plugin")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Scanned Author")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://github.com/scanned/plugin")).toBeInTheDocument();
    expect(screen.getByText("Metadata notes")).toBeInTheDocument();
    expect(screen.getByText("requirements.txt was not found")).toBeInTheDocument();
  });

  it("validates, copies, and opens a GitHub issue with the normalized submission payload", async () => {
    renderDialog();
    fillValidForm();

    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() =>
      expect(pluginMocks.validatePluginSubmission).toHaveBeenCalledWith(
        expect.objectContaining({
          author: "Alice",
          display_name: "Vision Helper",
          lowest_shinsekai_version: ">=0.3.0",
          repo: "https://github.com/alice/vision-helper.git",
          social_link: "https://github.com/alice",
          tags: ["vision", "helper", "tts"],
        }),
      ),
    );
    expect(screen.getByText("{\"ok\":true}")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy payload" }));
    await waitFor(() => expect(pluginMocks.copyPluginSubmissionJson).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Submit to GitHub Issue" }));
    await waitFor(() => expect(pluginMocks.buildPluginSubmissionIssueUrl).toHaveBeenCalledTimes(1));
    expect(fileMocks.openExternal).toHaveBeenCalledWith(
      "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new?template=PLUGIN_PUBLISH.yml",
    );
  });

  it("shows local and server validation errors and closes through the cancel action", async () => {
    const { onClose } = renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Submit plugin to market" });

    expect(within(dialog).getByRole("button", { name: "Validate" })).toBeDisabled();
    expect(screen.getByText("Plugin name is required.")).toBeInTheDocument();

    fillValidForm();
    pluginMocks.validatePluginSubmission.mockResolvedValueOnce({
      errors: ["Repository is not reachable"],
      json: "{\"ok\":false}",
      ok: false,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Validate" }));

    expect(await screen.findByText("Repository is not reachable")).toBeInTheDocument();
    expect(screen.getByText("{\"ok\":false}")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
