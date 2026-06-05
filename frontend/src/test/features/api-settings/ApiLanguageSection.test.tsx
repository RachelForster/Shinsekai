import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiLanguageSection } from "../../../features/api-settings/ApiLanguageSection";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { SystemConfig } from "../../../entities/config/types";

function systemConfig(overrides: Partial<SystemConfig> = {}): SystemConfig {
  return {
    ui_language: "en",
    ...overrides,
  } as SystemConfig;
}

function renderSection(overrides: Partial<Parameters<typeof ApiLanguageSection>[0]> = {}) {
  const props: Parameters<typeof ApiLanguageSection>[0] = {
    disabled: false,
    onChange: vi.fn(),
    systemDraft: systemConfig(),
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <ApiLanguageSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("ApiLanguageSection", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-color-scheme");
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });
  });

  it("normalizes language selection before notifying the parent draft", () => {
    const { props } = renderSection();

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Japanese" }));

    expect(props.onChange).toHaveBeenCalledWith("ja");
  });

  it("persists color scheme changes outside the API draft", () => {
    renderSection();

    expect(document.documentElement).toHaveAttribute("data-color-scheme", "light");

    fireEvent.click(screen.getByLabelText("Dark mode"));

    expect(document.documentElement).toHaveAttribute("data-color-scheme", "dark");
    expect(localStorage.getItem("shinsekai-color-scheme")).toBe("dark");
  });
});
