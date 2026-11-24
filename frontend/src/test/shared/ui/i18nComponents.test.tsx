import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { apiConfigFormSchema, validatePayloadFromSchema } from "../../../entities/config/schema";
import type { FormGroupSchema } from "../../../shared/form-schema";
import { I18nProvider, translateMessage } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ErrorBoundary, SchemaDrivenForm, TaskProgress } from "../../../shared/ui";

interface DemoDraft {
  builtinField: string;
  pluginField: string;
}

function ThrowError(): never {
  throw new Error("boom");
}

describe("Stage P4 shared UI i18n primitives", () => {
  it("resolves *Key schema descriptors via I18nProvider while preserving raw plugin string fallbacks", () => {
    const groups: Array<FormGroupSchema<DemoDraft>> = [
      {
        descriptionKey: "api.schema.llm.description",
        fields: [
          {
            labelKey: "api.schema.tts.provider",
            name: "builtinField",
            options: [{ labelKey: "domain.llmProvider.doubao", value: "doubao" }],
            type: "select",
          },
          {
            description: "External plugin field help",
            disabledReason: "Locked by external plugin",
            disabledWhen: () => true,
            label: "Plugin Raw Label",
            name: "pluginField",
            placeholder: "Plugin Raw Placeholder",
            type: "text",
          },
        ],
        id: "demo",
        titleKey: "api.schema.llm.title",
      },
    ];

    render(
      <I18nProvider language="en">
        <SchemaDrivenForm
          groups={groups}
          onChange={() => undefined}
          value={{ builtinField: "doubao", pluginField: "" }}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: translateMessage("en", "api.schema.llm.title") })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: translateMessage("en", "api.schema.tts.provider") })).toHaveTextContent(
      "Doubao",
    );
    expect(screen.getByText("Plugin Raw Label")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Plugin Raw Placeholder")).toBeDisabled();
    expect(screen.getByText("Locked by external plugin")).toBeInTheDocument();
  });

  it("localizes schema validation errors when passed an active translator", () => {
    const invalidDraft = {
      ...sampleConfig.api_config,
      compact_target_ratio: 0.9,
      compact_threshold: 0.4,
    };
    const enErrors = validatePayloadFromSchema(apiConfigFormSchema, invalidDraft, (key, values) =>
      translateMessage("en", key, values),
    );
    expect(enErrors.compact_target_ratio).toBe(translateMessage("en", "form.validation.max", { max: 0.35 }));
  });

  it("localizes TaskProgress phase, package status, and dependency status under I18nProvider", () => {
    render(
      <I18nProvider language="en">
        <TaskProgress
          task={{
            dependencyInstallStatus: "pip_ok",
            installSource: "github",
            packageStatus: "downloading",
            phase: "install",
            progress: 0.5,
            status: "running",
          }}
        />
      </I18nProvider>,
    );

    expect(screen.getByText(translateMessage("en", "task.phase.install"))).toBeInTheDocument();
    expect(screen.getByText(translateMessage("en", "task.packageStatus.downloading"))).toBeInTheDocument();
    expect(screen.getByText(translateMessage("en", "task.depStatus.pip_ok"))).toBeInTheDocument();
    expect(screen.getByText(translateMessage("en", "task.installSource.github"))).toBeInTheDocument();
  });

  it("localizes ErrorBoundary fallback title and retry action under I18nProvider", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      render(
        <I18nProvider language="ja">
          <ErrorBoundary>
            <ThrowError />
          </ErrorBoundary>
        </I18nProvider>,
      );

      expect(screen.getByRole("heading", { name: translateMessage("ja", "errorBoundary.title") })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: translateMessage("ja", "common.retry") })).toBeInTheDocument();
    } finally {
      consoleSpy.mockRestore();
    }
  });
});
