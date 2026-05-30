import {
  adapterExtraSchemaToFormGroup,
  defaultAdapterExtraValue,
  type AdapterExtraFormValues,
} from "../../entities/config/schema";
import type { AdapterExtraFieldSchema } from "../../entities/config/types";
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
  const entries = Object.entries(schema);
  if (!entries.length) {
    return null;
  }

  const disabledKeys = modelUnsupportedThinking ? ["thinking_enabled", "reasoning_effort"] : [];
  const group = adapterExtraSchemaToFormGroup({
    disabledKeys,
    disabledReason: "该模型不支持思考模式。",
    id: "adapter-extra",
    schema,
    title: "扩展参数",
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
