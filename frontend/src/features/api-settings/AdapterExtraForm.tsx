import {
  adapterExtraSchemaToFormGroup,
  defaultAdapterExtraValue,
  type AdapterExtraFormValues,
} from "../../entities/config/schema";
import type { AdapterExtraFieldSchema } from "../../entities/config/types";
import { useOptionalI18n } from "../../shared/i18n";
import { SchemaFieldGrid } from "../../shared/ui";

interface AdapterExtraFormProps {
  disabled?: boolean;
  modelUnsupportedThinking?: boolean;
  onChange: (key: string, value: unknown) => void;
  schema: Record<string, AdapterExtraFieldSchema>;
  values: Record<string, unknown>;
}

export function AdapterExtraForm({
  disabled,
  modelUnsupportedThinking = false,
  onChange,
  schema,
  values,
}: AdapterExtraFormProps) {
  const { t } = useOptionalI18n();
  const entries = Object.entries(schema);
  if (!entries.length) {
    return null;
  }

  const disabledKeys = modelUnsupportedThinking ? ["thinking_enabled", "reasoning_effort"] : [];
  const group = adapterExtraSchemaToFormGroup({
    disabledKeys,
    disabledReason: t("ops.api.extra.thinkingUnsupported"),
    id: "adapter-extra",
    schema,
    title: t("ops.api.extra.title"),
  });
  const displayValues = entries.reduce<AdapterExtraFormValues>((accumulator, [key, field]) => {
    accumulator[key] = values[key] ?? defaultAdapterExtraValue(field);
    if (modelUnsupportedThinking && key === "thinking_enabled") {
      accumulator[key] = false;
    }
    return accumulator;
  }, {});

  return (
    <SchemaFieldGrid
      className="api-extra-grid"
      disabled={disabled}
      group={group}
      onChange={(nextValues) => {
        for (const [key, value] of Object.entries(nextValues)) {
          if (!Object.is(value, displayValues[key])) {
            onChange(key, value);
            return;
          }
        }
      }}
      value={displayValues}
    />
  );
}
