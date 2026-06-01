import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FormGroupSchema } from "../../../shared/form-schema";
import { I18nProvider } from "../../../shared/i18n";
import { SchemaDrivenForm } from "../../../shared/ui/SchemaDrivenForm";

interface DraftConfig {
  count: number;
  enabled: boolean;
  hidden: string;
  locked: string;
  meta: Record<string, unknown>;
  name: string;
}

const value: DraftConfig = {
  count: 1,
  enabled: false,
  hidden: "secret",
  locked: "readonly",
  meta: { level: 1 },
  name: "Old name",
};

const groups: Array<FormGroupSchema<DraftConfig>> = [
  {
    description: "基础字段",
    fields: [
      { label: "Name", name: "name", placeholder: "Name", type: "text" },
      { label: "Count", max: (draft) => (draft.enabled ? 10 : 3), min: 0, name: "count", type: "integer" },
      { label: "Enabled", name: "enabled", type: "checkbox" },
      {
        disabledReason: "Enable first",
        disabledWhen: (draft) => !draft.enabled,
        label: "Locked",
        name: "locked",
        type: "text",
      },
      { label: "Hidden", name: "hidden", type: "text", visibleWhen: (draft) => draft.enabled },
      { label: "Meta", name: "meta", span: "full", type: "json" },
    ],
    id: "base",
    title: "Base",
  },
];

function renderForm(onChange = vi.fn(), draft: DraftConfig = value, collapsedGroupIds: string[] = []) {
  render(
    <I18nProvider language="zh_CN">
      <SchemaDrivenForm collapsedGroupIds={collapsedGroupIds} groups={groups} onChange={onChange} value={draft} />
    </I18nProvider>,
  );
  return onChange;
}

describe("SchemaDrivenForm", () => {
  it("maps primitive fields back into draft updates", () => {
    const onChange = renderForm();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Nanami" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...value, name: "Nanami" });

    fireEvent.change(screen.getByLabelText("Count"), { target: { value: "2" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...value, count: 2 });

    fireEvent.click(screen.getByRole("checkbox", { name: "Enabled" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...value, enabled: true });
  });

  it("honors visibility, disabled reasons, and collapsed groups", () => {
    renderForm(vi.fn(), value, ["base"]);

    expect(screen.getByText("Base")).toBeInTheDocument();
    expect(screen.getByDisplayValue("readonly")).toBeDisabled();
    expect(screen.getByText("Enable first")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("secret")).not.toBeInTheDocument();
  });

  it("commits valid JSON and reports invalid JSON", () => {
    const onChange = renderForm();
    const meta = screen.getByLabelText("Meta");

    fireEvent.change(meta, { target: { value: '{"level":2}' } });
    fireEvent.blur(meta);
    expect(onChange).toHaveBeenLastCalledWith({ ...value, meta: { level: 2 } });

    fireEvent.change(meta, { target: { value: "{" } });
    fireEvent.blur(meta);
    expect(screen.getByText(/JSON/)).toBeInTheDocument();
  });
});
