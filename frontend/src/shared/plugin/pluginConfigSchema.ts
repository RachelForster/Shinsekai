import type { FieldKind, FormGroupSchema } from "../form-schema";
import type { PluginConfigFieldType, PluginConfigGroupSchema } from "../platform/types";

export type PluginConfigDraft = Record<string, unknown>;

export function pluginFieldTypeToFormType(type: PluginConfigFieldType): FieldKind {
  if (type === "boolean") {
    return "checkbox";
  }
  return type;
}

export function pluginConfigGroupsToFormGroups(
  groups: PluginConfigGroupSchema[],
): Array<FormGroupSchema<PluginConfigDraft>> {
  return groups.map((group) => ({
    columns: 1,
    description: group.description,
    fields: group.fields.map((field) => ({
      defaultValue: field.defaultValue,
      description: field.description,
      label: field.label,
      max: field.max,
      min: field.min,
      name: field.key,
      options: field.options,
      pathKind: field.pathKind,
      placeholder: field.placeholder,
      required: field.required,
      span: field.span,
      step: field.step,
      type: pluginFieldTypeToFormType(field.type),
      visibleWhen: field.visibleWhen
        ? (draft) => Object.entries(field.visibleWhen!).every(([key, expected]) => draft[key] === expected)
        : undefined,
    })),
    id: group.id,
    title: group.title,
  }));
}

export function pluginConfigInitialValues(source: {
  schema?: PluginConfigGroupSchema[];
  values?: Record<string, unknown>;
}): PluginConfigDraft {
  const values = source.values ?? {};
  const draft: PluginConfigDraft = {};
  for (const group of source.schema ?? []) {
    for (const field of group.fields) {
      draft[field.key] = Object.prototype.hasOwnProperty.call(values, field.key)
        ? values[field.key]
        : field.defaultValue;
    }
  }
  return draft;
}
