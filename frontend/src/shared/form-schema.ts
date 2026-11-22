import type { TranslateFn } from "./i18n/I18nProvider";
import type { MessageKey } from "./i18n/messages";

export type FieldKind =
  | "checkbox"
  | "color"
  | "file"
  | "integer"
  | "json"
  | "number"
  | "password"
  | "select"
  | "text"
  | "textarea"
  | "url";

export interface FormOption {
  label?: string;
  labelKey?: MessageKey;
  value: string;
}

export type NumericBound<T extends object> = number | ((draft: T) => number);

export interface FormFieldSchema<T extends object> {
  defaultValue?: unknown;
  description?: string;
  descriptionKey?: MessageKey;
  disabledReason?: string | ((draft: T) => string | undefined);
  disabledReasonKey?: MessageKey;
  disabledWhen?: (draft: T) => boolean;
  label?: string;
  labelKey?: MessageKey;
  max?: NumericBound<T>;
  min?: NumericBound<T>;
  name: keyof T;
  options?: FormOption[];
  pathKind?: "directory" | "file";
  placeholder?: string;
  placeholderKey?: MessageKey;
  required?: boolean;
  span?: "full";
  step?: number;
  type: FieldKind;
  visibleWhen?: (draft: T) => boolean;
}

export interface FormGroupSchema<T extends object> {
  columns?: 1 | 2;
  description?: string;
  descriptionKey?: MessageKey;
  fields: Array<FormFieldSchema<T>>;
  id: string;
  title?: string;
  titleKey?: MessageKey;
}

export function resolveFormOptionLabel(option: FormOption, t: TranslateFn): string {
  if (option.labelKey) {
    return t(option.labelKey);
  }
  return option.label ?? option.value;
}

export function resolveFormFieldLabel<T extends object>(field: FormFieldSchema<T>, t: TranslateFn): string {
  if (field.labelKey) {
    return t(field.labelKey);
  }
  return field.label ?? String(field.name);
}

export function resolveFormFieldDescription<T extends object>(
  field: FormFieldSchema<T>,
  t: TranslateFn,
): string | undefined {
  if (field.descriptionKey) {
    return t(field.descriptionKey);
  }
  return field.description;
}

export function resolveFormFieldPlaceholder<T extends object>(
  field: FormFieldSchema<T>,
  t: TranslateFn,
): string | undefined {
  if (field.placeholderKey) {
    return t(field.placeholderKey);
  }
  return field.placeholder;
}

export function resolveFormFieldDisabledReason<T extends object>(
  field: FormFieldSchema<T>,
  draft: T,
  t: TranslateFn,
): string | undefined {
  if (typeof field.disabledReason === "function") {
    return field.disabledReason(draft);
  }
  if (field.disabledReason !== undefined) {
    return field.disabledReason;
  }
  if (field.disabledReasonKey) {
    return t(field.disabledReasonKey);
  }
  return undefined;
}

export function resolveFormGroupTitle<T extends object>(group: FormGroupSchema<T>, t: TranslateFn): string {
  if (group.titleKey) {
    return t(group.titleKey);
  }
  return group.title ?? group.id;
}

export function resolveFormGroupDescription<T extends object>(
  group: FormGroupSchema<T>,
  t: TranslateFn,
): string | undefined {
  if (group.descriptionKey) {
    return t(group.descriptionKey);
  }
  return group.description;
}
