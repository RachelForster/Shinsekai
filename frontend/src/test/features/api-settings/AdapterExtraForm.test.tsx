import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdapterExtraForm } from "../../../features/api-settings/AdapterExtraForm";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderForm(overrides: Partial<Parameters<typeof AdapterExtraForm>[0]> = {}) {
  const props: Parameters<typeof AdapterExtraForm>[0] = {
    onChange: vi.fn(),
    schema: {
      reasoning_effort: { choices: ["low", "medium", "high"], default: "medium", label: "Reasoning effort" },
      temperature: { default: 0.6, label: "Temperature", max: 2, min: 0, step: 0.1, type: "float" },
      thinking_enabled: { default: true, label: "Thinking", type: "bool" },
    },
    values: { reasoning_effort: "medium", temperature: 0.6, thinking_enabled: true },
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <AdapterExtraForm {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("AdapterExtraForm", () => {
  it("routes schema field changes through the changed adapter key", () => {
    const { props } = renderForm();

    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.9" } });
    expect(props.onChange).toHaveBeenCalledWith("temperature", 0.9);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "high" }));
    expect(props.onChange).toHaveBeenCalledWith("reasoning_effort", "high");
  });

  it("disables thinking controls when the selected model cannot use them", () => {
    renderForm({ modelUnsupportedThinking: true });

    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
