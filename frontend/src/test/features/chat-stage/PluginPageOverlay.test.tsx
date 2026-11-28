import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PluginPageOverlay } from "../../../features/chat-stage/components/PluginPageOverlay";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { ChatBehaviorState, PluginBehaviorEvent } from "../../../shared/platform/types";
import type { PluginPageTarget } from "../../../shared/plugin/PluginSlot";

const repository = vi.hoisted(() => ({
  getUi: vi.fn(),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  getPluginUiDetail: (pluginId: string) => repository.getUi(pluginId),
}));

function renderOverlay(
  onClose = vi.fn(),
  target: PluginPageTarget = {
    mode: "overlay",
    pageId: "dashboard",
    pluginId: "demo.plugin",
  },
) {
  render(
    <I18nProvider language="en">
      <PluginPageOverlay onClose={onClose} target={target} />
    </I18nProvider>,
  );
  return onClose;
}

describe("PluginPageOverlay", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    window.history.replaceState({}, "", "/");
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 620, writable: true });
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360, writable: true });
    repository.getUi.mockReset().mockResolvedValue({
      pages: [
        {
          frontendUrl:
            "/api/plugins/demo.plugin/frontend/dashboard/?pluginId=demo.plugin&pageId=dashboard&shinsekai_bridge_token=secret",
          id: "dashboard",
          kind: "tools",
          order: 10,
          pluginId: "demo.plugin",
          pluginVersion: "1.0.0",
          title: "Dashboard",
        },
      ],
      plugin: { id: "demo.plugin" },
    });
  });

  it("loads the registered page through the configured bridge and stays inside a small viewport", async () => {
    vi.stubEnv("VITE_SHINSEKAI_API_BASE", "http://127.0.0.1:8787");
    renderOverlay();

    const frame = (await screen.findByTitle("Dashboard")) as HTMLIFrameElement;
    const overlay = screen.getByRole("dialog", { name: "Dashboard" });

    expect(repository.getUi).toHaveBeenCalledWith("demo.plugin");
    expect(frame.src).toBe(
      "http://127.0.0.1:8787/api/plugins/demo.plugin/frontend/dashboard/" +
        "?pluginId=demo.plugin&pageId=dashboard&shinsekai_bridge_token=secret",
    );
    expect(overlay).toHaveStyle({ height: "604px", left: "8px", top: "8px", width: "344px" });
  });

  it("closes from the host button and rejects pages not owned by the target plugin", async () => {
    repository.getUi.mockResolvedValue({
      pages: [
        {
          frontendUrl: "/api/plugins/other/frontend/dashboard/",
          id: "dashboard",
          kind: "tools",
          order: 10,
          pluginId: "other.plugin",
          pluginVersion: "1.0.0",
          title: "Wrong owner",
        },
      ],
      plugin: { id: "demo.plugin" },
    });
    const onClose = renderOverlay();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTitle("Wrong owner")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close" }), { detail: 0 });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("clamps iframe-driven dragging so the host controls remain visible", async () => {
    renderOverlay();
    const frame = (await screen.findByTitle("Dashboard")) as HTMLIFrameElement;
    const overlay = screen.getByRole("dialog", { name: "Dashboard" });

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { __pluginOverlay: "drag", type: "start" },
          source: frame.contentWindow,
        }),
      );
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { __pluginOverlay: "drag", dx: 10_000, dy: 10_000, type: "move" },
          source: frame.contentWindow,
        }),
      );
    });

    await waitFor(() => expect(overlay).toHaveStyle({ left: "8px", top: "8px" }));
  });

  it("delivers a runtime presentation payload only to the registered page origin", async () => {
    vi.stubEnv("VITE_SHINSEKAI_API_BASE", "http://127.0.0.1:8787");
    renderOverlay(vi.fn(), {
      mode: "overlay",
      pageId: "dashboard",
      payload: { kind: "reminder", title: "Tea is ready" },
      pluginId: "demo.plugin",
      presentationId: "notice-42",
    });
    const frame = (await screen.findByTitle("Dashboard")) as HTMLIFrameElement;
    const postMessage = vi.spyOn(frame.contentWindow!, "postMessage");

    fireEvent.load(frame);

    expect(postMessage).toHaveBeenLastCalledWith(
      {
        __shinsekai: "plugin-page",
        payload: { kind: "reminder", title: "Tea is ready" },
        presentationId: "notice-42",
        type: "present",
      },
      "http://127.0.0.1:8787",
    );
  });

  it("forwards matching behavior state and buffers pre-load behavior events per plugin", async () => {
    vi.stubEnv("VITE_SHINSEKAI_API_BASE", "http://127.0.0.1:8787");
    const listeners = new Set<(event: PluginBehaviorEvent) => void>();
    const emit = (event: PluginBehaviorEvent) => {
      for (const listener of listeners) listener(event);
    };
    const subscribe = (listener: (event: PluginBehaviorEvent) => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    };
    const matchingBehavior: ChatBehaviorState = {
      behaviorId: "werewolf",
      hud: { phase: "night", round: 1 },
      pluginId: "demo.plugin",
      stagePolicy: {
        allowFreeTextInterject: true,
        allowUnboundSpeakers: true,
        hideInputLayer: false,
        playbackEndAction: "idle",
      },
      stateVersion: 1,
    };
    const foreignBehavior: ChatBehaviorState = {
      behaviorId: "other",
      hud: { secret: true },
      pluginId: "other.plugin",
      stagePolicy: {
        allowFreeTextInterject: true,
        allowUnboundSpeakers: true,
        hideInputLayer: false,
        playbackEndAction: "idle",
      },
      stateVersion: 1,
    };
    const target: PluginPageTarget = {
      mode: "overlay",
      pageId: "dashboard",
      pluginId: "demo.plugin",
    };

    const { rerender } = render(
      <I18nProvider language="en">
        <PluginPageOverlay
          behavior={matchingBehavior}
          onClose={vi.fn()}
          subscribeBehaviorEvents={subscribe}
          target={target}
        />
      </I18nProvider>,
    );

    // Emit before iframe finishes loading: only matching plugin events should buffer.
    emit({ eventType: "phase.changed", payload: { phase: "night" }, pluginId: "demo.plugin", seq: 4 });
    emit({ eventType: "foreign.secret", payload: {}, pluginId: "other.plugin", seq: 5 });

    const frame = (await screen.findByTitle("Dashboard")) as HTMLIFrameElement;
    const postMessage = vi.spyOn(frame.contentWindow!, "postMessage");

    fireEvent.load(frame);

    expect(postMessage).toHaveBeenNthCalledWith(
      1,
      {
        __shinsekai: "plugin-page",
        behavior: matchingBehavior,
        type: "behavior.state",
      },
      "http://127.0.0.1:8787",
    );
    expect(postMessage).toHaveBeenNthCalledWith(
      2,
      {
        __shinsekai: "plugin-page",
        eventType: "phase.changed",
        payload: { phase: "night" },
        pluginId: "demo.plugin",
        seq: 4,
        type: "behavior.event",
      },
      "http://127.0.0.1:8787",
    );
    expect(postMessage).toHaveBeenCalledTimes(2);

    // Live events and behavior detachment
    act(() => {
      emit({ eventType: "vote.cast", payload: { target: "Nanami" }, pluginId: "demo.plugin", seq: 6 });
      emit({ eventType: "other.vote", payload: {}, pluginId: "other.plugin", seq: 7 });
    });
    expect(postMessage).toHaveBeenLastCalledWith(
      {
        __shinsekai: "plugin-page",
        eventType: "vote.cast",
        payload: { target: "Nanami" },
        pluginId: "demo.plugin",
        seq: 6,
        type: "behavior.event",
      },
      "http://127.0.0.1:8787",
    );
    expect(postMessage).toHaveBeenCalledTimes(3);

    // Re-rendering with another plugin's behavior must not post foreign state.
    rerender(
      <I18nProvider language="en">
        <PluginPageOverlay
          behavior={foreignBehavior}
          onClose={vi.fn()}
          subscribeBehaviorEvents={subscribe}
          target={target}
        />
      </I18nProvider>,
    );
    expect(postMessage).toHaveBeenCalledTimes(3);
  });
});
