import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FormGroupSchema } from "../../../shared/form-schema";
import { I18nProvider } from "../../../shared/i18n";
import { SchemaDrivenForm } from "../../../shared/ui";

interface DraftConfig {
  count: number;
  enabled: boolean;
  extra: unknown;
  hidden: string;
  locked: string;
  mode: string;
  name: string;
}

const value: DraftConfig = {
  count: 1,
  enabled: false,
  extra: { retries: 1 },
  hidden: "secret",
  locked: "readonly",
  mode: "auto",
  name: "Miku",
};

const groups: Array<FormGroupSchema<DraftConfig>> = [
  {
    description: "Basic fields",
    fields: [
      { label: "Name", name: "name", placeholder: "Name", type: "text" },
      { label: "Count", max: (draft) => (draft.enabled ? 10 : 3), min: 0, name: "count", type: "integer" },
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
      {
        disabledReason: "Enable first",
        disabledWhen: (draft) => !draft.enabled,
        label: "Locked",
        name: "locked",
        type: "text",
      },
      { label: "Hidden", name: "hidden", type: "text", visibleWhen: (draft) => draft.enabled },
      { label: "Extra JSON", name: "extra", span: "full", type: "json" },
    ],
    id: "base",
    title: "Base",
  },
];

function renderForm(draft: DraftConfig = value, onChange = vi.fn(), collapsedGroupIds: string[] = []) {
  render(
    <I18nProvider language="en">
      <SchemaDrivenForm collapsedGroupIds={collapsedGroupIds} groups={groups} onChange={onChange} value={draft} />
    </I18nProvider>,
  );
  return onChange;
}

describe("SchemaDrivenForm", () => {
  it("emits primitive field changes without mutating the original draft", () => {
    const onChange = renderForm(value);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Rin" } });
    fireEvent.change(screen.getByLabelText("Count"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Manual" }));

    expect(onChange).toHaveBeenNthCalledWith(1, { ...value, name: "Rin" });
    expect(onChange).toHaveBeenNthCalledWith(2, { ...value, count: 2 });
    expect(onChange).toHaveBeenNthCalledWith(3, { ...value, enabled: true });
    expect(onChange).toHaveBeenNthCalledWith(4, { ...value, mode: "manual" });
    expect(value).toEqual({
      count: 1,
      enabled: false,
      extra: { retries: 1 },
      hidden: "secret",
      locked: "readonly",
      mode: "auto",
      name: "Miku",
    });
  });

  it("honors visibility, disabled reasons, and collapsed groups", () => {
    renderForm(value, vi.fn(), ["base"]);

    expect(screen.getByText("Base")).toBeInTheDocument();
    expect(screen.getByDisplayValue("readonly")).toBeDisabled();
    expect(screen.getByText("Enable first")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("secret")).not.toBeInTheDocument();
  });

  it("commits valid JSON on blur", () => {
    const onChange = renderForm();
    const extra = screen.getByLabelText("Extra JSON");

    fireEvent.change(extra, { target: { value: '{"retries":2}' } });
    fireEvent.blur(extra);

    expect(onChange).toHaveBeenCalledWith({ ...value, extra: { retries: 2 } });
    expect(screen.queryByText("Invalid JSON. Fix it before saving.")).not.toBeInTheDocument();
  });

  it("shows an error and keeps the draft unchanged when JSON is invalid", () => {
    const onChange = renderForm();
    const extra = screen.getByLabelText("Extra JSON");

    fireEvent.change(extra, { target: { value: '{"retries":' } });
    fireEvent.blur(extra);

    expect(screen.getByText("Invalid JSON. Fix it before saving.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
