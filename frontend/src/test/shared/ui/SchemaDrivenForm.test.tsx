import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FormGroupSchema } from "../../../shared/form-schema";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { SchemaDrivenForm } from "../../../shared/ui";

interface Draft {
  enabled: boolean;
  extra: unknown;
  mode: string;
  name: string;
}

const groups: Array<FormGroupSchema<Draft>> = [
  {
    fields: [
      { label: "Name", name: "name", type: "text" },
      { label: "Enabled", name: "enabled", type: "checkbox" },
      {
        label: "Mode",
        name: "mode",
        options: [
          { label: "Automatic", value: "auto" },
          { label: "Manual", value: "manual" },
        ],
        type: "select",
      },
      { label: "Extra JSON", name: "extra", type: "json" },
    ],
    id: "main",
    title: "Main",
  },
];

function renderForm(value: Draft, onChange = vi.fn()) {
  render(
    <I18nProvider language="en">
      <SchemaDrivenForm groups={groups} onChange={onChange} value={value} />
    </I18nProvider>,
  );
  return onChange;
}

describe("SchemaDrivenForm", () => {
  it("emits text, checkbox, and select changes without mutating the original draft", () => {
    const value: Draft = { enabled: false, extra: { retries: 1 }, mode: "auto", name: "Miku" };
    const onChange = renderForm(value);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Rin" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Manual" }));

    expect(onChange).toHaveBeenNthCalledWith(1, { ...value, name: "Rin" });
    expect(onChange).toHaveBeenNthCalledWith(2, { ...value, enabled: true });
    expect(onChange).toHaveBeenNthCalledWith(3, { ...value, mode: "manual" });
    expect(value).toEqual({ enabled: false, extra: { retries: 1 }, mode: "auto", name: "Miku" });
  });

  it("parses JSON values on blur", () => {
    const value: Draft = { enabled: true, extra: { retries: 1 }, mode: "auto", name: "Miku" };
    const onChange = renderForm(value);

    fireEvent.change(screen.getByLabelText("Extra JSON"), { target: { value: '{"retries":2}' } });
    fireEvent.blur(screen.getByLabelText("Extra JSON"));

    expect(onChange).toHaveBeenCalledWith({ ...value, extra: { retries: 2 } });
    expect(screen.queryByText("Invalid JSON. Fix it before saving.")).not.toBeInTheDocument();
  });

  it("shows an error and keeps the draft unchanged when JSON is invalid", () => {
    const value: Draft = { enabled: true, extra: { retries: 1 }, mode: "auto", name: "Miku" };
    const onChange = renderForm(value);

    fireEvent.change(screen.getByLabelText("Extra JSON"), { target: { value: '{"retries":' } });
    fireEvent.blur(screen.getByLabelText("Extra JSON"));

    expect(screen.getByText("Invalid JSON. Fix it before saving.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
