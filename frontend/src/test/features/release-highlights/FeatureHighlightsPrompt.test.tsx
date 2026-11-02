import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FeatureHighlightsPrompt } from "../../../features/release-highlights/FeatureHighlightsPrompt";
import { FEATURE_HIGHLIGHTS_SEEN_KEY } from "../../../features/release-highlights/releaseHighlightsState";
import { getInitialSettingsPath } from "../../../features/onboarding/onboardingState";
import { I18nProvider } from "../../../shared/i18n";

const updateInfoMocks = vi.hoisted(() => ({ useAppUpdateInfo: vi.fn() }));

vi.mock("../../../app/shell/useAppUpdateInfo", () => ({
  useAppUpdateInfo: updateInfoMocks.useAppUpdateInfo,
}));

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderPrompt(enabled = true) {
  return render(
    <I18nProvider language="en">
      <MemoryRouter
        future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
        initialEntries={["/settings/templates"]}
      >
        <FeatureHighlightsPrompt enabled={enabled} />
        <LocationProbe />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("FeatureHighlightsPrompt", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("shinsekai-onboarding-seen", "true");
    updateInfoMocks.useAppUpdateInfo.mockReturnValue({ data: { version: "2.3.0" } });
  });

  it("shows an unseen release once and persists dismissal", async () => {
    renderPrompt();

    const dialog = await screen.findByRole("dialog", { name: "What's new" });
    expect(dialog).toHaveTextContent("Design your own Chat UI");
    expect(dialog).toHaveTextContent("Live preview with real components");

    fireEvent.click(screen.getByRole("button", { name: "Got it" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "What's new" })).not.toBeInTheDocument());
    expect(localStorage.getItem(FEATURE_HIGHLIGHTS_SEEN_KEY)).toBe("2.3.0");
  });

  it("silently establishes a baseline on first install", async () => {
    localStorage.clear();
    expect(getInitialSettingsPath()).toBe("/settings/onboarding");

    renderPrompt();

    expect(screen.queryByRole("dialog", { name: "What's new" })).not.toBeInTheDocument();
    await waitFor(() => expect(localStorage.getItem(FEATURE_HIGHLIGHTS_SEEN_KEY)).toBe("2.3.0"));
  });

  it("also treats a fresh profile opened through a deep link as a first install", async () => {
    localStorage.clear();

    renderPrompt();

    expect(screen.queryByRole("dialog", { name: "What's new" })).not.toBeInTheDocument();
    await waitFor(() => expect(localStorage.getItem(FEATURE_HIGHLIGHTS_SEEN_KEY)).toBe("2.3.0"));
  });

  it("marks the release seen and navigates from the primary action", async () => {
    renderPrompt();

    fireEvent.click(await screen.findByRole("button", { name: "Open theme editor" }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/settings/system/chat-themes/customize"),
    );
    expect(localStorage.getItem(FEATURE_HIGHLIGHTS_SEEN_KEY)).toBe("2.3.0");
  });

  it("waits until startup update checks allow it to open", () => {
    renderPrompt(false);

    expect(screen.queryByRole("dialog", { name: "What's new" })).not.toBeInTheDocument();
  });
});
