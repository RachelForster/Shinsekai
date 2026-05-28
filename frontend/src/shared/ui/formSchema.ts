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
  label: string;
  value: string;
}

export interface FormFieldSchema<T extends object> {
  defaultValue?: unknown;
  description?: string;
  disabledReason?: string | ((draft: T) => string | undefined);
  disabledWhen?: (draft: T) => boolean;
  label: string;
  max?: number;
  min?: number;
  name: keyof T;
  options?: FormOption[];
  pathKind?: "directory" | "file";
  placeholder?: string;
  required?: boolean;
  span?: "full";
  step?: number;
  type: FieldKind;
  visibleWhen?: (draft: T) => boolean;
}

export interface FormGroupSchema<T extends object> {
  columns?: 1 | 2;
  description?: string;
  fields: Array<FormFieldSchema<T>>;
  id: string;
  title: string;
}
