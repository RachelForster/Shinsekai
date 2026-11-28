import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, type FrontendLanguage } from "../../../shared/i18n";
import { PluginIframeHost } from "../../../shared/plugin/PluginIframeHost";
import { applyThemeColor } from "../../../shared/theme/appTheme";

describe("PluginIframeHost", () => {
  beforeEach(() => {
    document.documentElement.style.removeProperty("--theme-accent");
    document.documentElement.setAttribute("data-density", "compact");
  });

  afterEach(() => {
    document.documentElement.removeAttribute("data-density");
  });

  it("embeds initial SDK params without losing tokens and syncs live updates via postMessage", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const postMessage = vi.fn();

    function Harness() {
      const [language, setLanguage] = useState<FrontendLanguage>("zh_CN");
      const [entityId, setEntityId] = useState("Alice");
      return (
        <QueryClientProvider client={queryClient}>
          <I18nProvider language={language}>
            <div data-density="compact">
              <button onClick={() => setLanguage("en")} type="button">
                Switch Lang
              </button>
              <button onClick={() => setEntityId("Bob")} type="button">
                Switch Entity
              </button>
              <PluginIframeHost
                context={{ entityId, entityType: "character", page: "character" }}
                frontendUrl="/api/plugins/demo/frontend/panel/?pluginId=demo&pageId=panel&shinsekai_bridge_token=tok123"
                maxHeight={500}
                minHeight={160}
                pluginId="demo"
                slot="body"
                surface="section"
                title="Demo Frame"
              />
            </div>
          </I18nProvider>
        </QueryClientProvider>
      );
    }

    render(<Harness />);
    const iframe = screen.getByTitle("Demo Frame") as HTMLIFrameElement;
    const initialSrc = iframe.getAttribute("src") ?? "";
    const parsed = new URL(initialSrc, "http://127.0.0.1");

    expect(parsed.pathname).toBe("/api/plugins/demo/frontend/panel/");
    expect(parsed.searchParams.get("shinsekai_bridge_token")).toBe("tok123");
    expect(parsed.searchParams.get("surface")).toBe("section");
    expect(parsed.searchParams.get("lang")).toBe("zh_CN");
    expect(parsed.searchParams.get("density")).toBe("compact");
    expect(parsed.searchParams.get("entityId")).toBe("Alice");
    expect(iframe.getAttribute("sandbox")).toBe("allow-forms allow-same-origin allow-scripts");

    Object.defineProperty(iframe, "contentWindow", { configurable: true, value: { postMessage } });
    await act(async () => {
      iframe.dispatchEvent(new Event("load"));
    });
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ __shinsekai: "plugin-host", type: "theme.change" }),
      window.location.origin,
    );

    postMessage.mockClear();
    await act(async () => {
      applyThemeColor("#336699");
      screen.getByRole("button", { name: "Switch Lang" }).click();
      screen.getByRole("button", { name: "Switch Entity" }).click();
    });

    // Live updates must NOT reload iframe src
    expect(iframe.getAttribute("src")).toBe(initialSrc);
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ __shinsekai: "plugin-host", language: "en", type: "locale.change" }),
      window.location.origin,
    );
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        __shinsekai: "plugin-host",
        context: expect.objectContaining({ entityId: "Bob" }),
        type: "context.change",
      }),
      window.location.origin,
    );

    // Resize messages clamp within [minHeight, maxHeight] and ignore foreign origins
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { __shinsekai: "plugin-host", height: 999, type: "resize" },
          origin: window.location.origin,
          source: iframe.contentWindow,
        }),
      );
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { __shinsekai: "plugin-host", height: 220, type: "resize" },
          origin: "https://evil.example",
          source: iframe.contentWindow,
        }),
      );
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { __shinsekai: "plugin-host", targets: ["characters", "templates"], type: "refresh" },
          origin: window.location.origin,
          source: iframe.contentWindow,
        }),
      );
    });

    expect(iframe.style.height).toBe("500px");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["characters"] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["templates"] });
  });
});
