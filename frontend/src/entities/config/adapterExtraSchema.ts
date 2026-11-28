import type { AdapterExtraFieldSchema } from "./types";
import type { FieldKind, FormGroupSchema } from "../../shared/form-schema";
import { isMessageKey } from "../../shared/i18n";

export type AdapterExtraFormValues = Record<string, unknown>;

export interface AdapterExtraFormGroupOptions {
  disabledKeys?: string[];
  disabledReason?: string;
  id: string;
  schema: Record<string, AdapterExtraFieldSchema>;
  title: string;
}

function adapterFieldType(field: AdapterExtraFieldSchema) {
  return String(field.type || "str").toLowerCase();
}

export function defaultAdapterExtraValue(field: AdapterExtraFieldSchema): unknown {
  const type = adapterFieldType(field);
  if (field.default !== undefined) {
    return field.default;
  }
  if (type === "bool") {
    return false;
  }
  if (type === "int" || type === "float") {
    return 0;
  }
  return "";
}

function adapterFieldKind(field: AdapterExtraFieldSchema): FieldKind {
  const type = adapterFieldType(field);
  if (Array.isArray(field.choices) && field.choices.length) {
    return "select";
  }
  if (type === "bool") {
    return "checkbox";
  }
  if (type === "int") {
    return "integer";
  }
  if (type === "float") {
    return "number";
  }
  return field.secret ? "password" : "text";
}

export function adapterExtraSchemaToFormGroup({
  disabledKeys = [],
  disabledReason,
  id,
  schema,
  title,
}: AdapterExtraFormGroupOptions): FormGroupSchema<AdapterExtraFormValues> {
  const disabledKeySet = new Set(disabledKeys);
  return {
    columns: 2,
    fields: Object.entries(schema).map(([key, field]) => {
      const type = adapterFieldType(field);
      const labelKey = field.labelKey && isMessageKey(field.labelKey) ? field.labelKey : undefined;
      return {
        defaultValue: defaultAdapterExtraValue(field),
        disabledReason: disabledKeySet.has(key) ? disabledReason : undefined,
        disabledWhen: disabledKeySet.has(key) ? () => true : undefined,
        label: field.label || key,
        labelKey,
        max: field.max,
        min: field.min,
        name: key,
        options: field.choices?.map((choice) => ({ label: choice, value: choice })),
        step: field.step ?? (type === "int" ? 1 : type === "float" ? 0.01 : undefined),
        type: adapterFieldKind(field),
      };
    }),
    id,
    title,
  };
}
