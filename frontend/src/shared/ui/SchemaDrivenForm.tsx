import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import { CircleHelp } from "lucide-react";

import { useI18n } from "../i18n";
import type { FormFieldSchema, FormGroupSchema } from "../form-schema";
import { ColorInput, FilePicker, NumberInput, Select, TextArea, TextInput } from "./FormControls";
import { Switch } from "./Switch";

export type SchemaErrorMap<T extends object> = Partial<Record<keyof T, string>>;

interface SchemaDrivenFormProps<T extends object> {
  collapsedGroupIds?: string[];
  disabled?: boolean;
  errors?: SchemaErrorMap<T>;
  groups: Array<FormGroupSchema<T>>;
  onChange: (draft: T) => void;
  value: T;
}

interface SchemaFieldGridProps<T extends object> {
  className?: string;
  disabled?: boolean;
  errors?: SchemaErrorMap<T>;
  group: FormGroupSchema<T>;
  onChange: (draft: T) => void;
  value: T;
}

function parseJson(text: string): unknown {
  if (!text.trim()) {
    return {};
  }
  return JSON.parse(text);
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function resolveDisabledReason<T extends object>(field: FormFieldSchema<T>, value: T) {
  if (typeof field.disabledReason === "function") {
    return field.disabledReason(value);
  }
  return field.disabledReason;
}

function resolveNumericBound<T extends object>(bound: FormFieldSchema<T>["max"] | FormFieldSchema<T>["min"], value: T) {
  return typeof bound === "function" ? bound(value) : bound;
}

function formGridClassName<T extends object>(group: FormGroupSchema<T>, className = "") {
  return ["form-grid", group.columns === 1 ? "form-grid--one" : "form-grid--two", className].filter(Boolean).join(" ");
}

export function SchemaFieldGrid<T extends object>({
  className = "",
  disabled = false,
  errors = {},
  group,
  onChange,
  value,
}: SchemaFieldGridProps<T>) {
  const { t } = useI18n();

  const update = <K extends keyof T>(name: K, next: T[K]) => {
    onChange({ ...value, [name]: next });
  };

  const renderField = (field: FormFieldSchema<T>) => {
    const rawValue = value[field.name] ?? field.defaultValue;
    const fieldDisabled = disabled || Boolean(field.disabledWhen?.(value));
    const common = {
      disabled: fieldDisabled,
      id: String(field.name),
    };

    if (field.type === "checkbox") {
      return (
        <Switch
          checked={Boolean(rawValue)}
          disabled={common.disabled}
          id={common.id}
          onChange={(event) => update(field.name, event.target.checked as T[keyof T])}
        />
      );
    }

    if (field.type === "select") {
      return (
        <Select
          {...common}
          onChange={(event) => update(field.name, event.target.value as T[keyof T])}
          value={String(rawValue ?? "")}
        >
          {(field.options ?? []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      );
    }

    if (field.type === "textarea") {
      return (
        <TextArea
          {...common}
          onChange={(event) => update(field.name, event.target.value as T[keyof T])}
          placeholder={field.placeholder}
          value={String(rawValue ?? "")}
        />
      );
    }

    if (field.type === "json") {
      return (
        <JsonField
          disabled={fieldDisabled}
          id={String(field.name)}
          onChange={(next) => update(field.name, next as T[keyof T])}
          value={rawValue}
        />
      );
    }

    if (field.type === "file") {
      return (
        <FilePicker
          {...common}
          onChange={(event) => update(field.name, event.target.value as T[keyof T])}
          onPathChange={(path) => update(field.name, path as T[keyof T])}
          pickLabel={field.pathKind === "directory" ? t("common.chooseFolder") : t("common.chooseFile")}
          pickerMode={field.pathKind ?? "file"}
          pickerTitle={field.label}
          placeholder={field.placeholder}
          value={String(rawValue ?? "")}
        />
      );
    }

    if (field.type === "number" || field.type === "integer") {
      const max = resolveNumericBound(field.max, value);
      const min = resolveNumericBound(field.min, value);
      return (
        <NumberInput
          {...common}
          max={max}
          min={min}
          onChange={(event: ChangeEvent<HTMLInputElement>) => {
            const next =
              field.type === "integer" ? Number.parseInt(event.target.value, 10) : Number(event.target.value);
            update(field.name, (Number.isNaN(next) ? 0 : next) as T[keyof T]);
          }}
          step={field.step}
          value={Number(rawValue ?? 0)}
        />
      );
    }

    if (field.type === "color") {
      return (
        <div className="input-group">
          <ColorInput
            {...common}
            onChange={(event) => update(field.name, event.target.value as T[keyof T])}
            value={String(rawValue ?? "")}
          />
          <span aria-hidden className="swatch" style={{ background: String(rawValue ?? "transparent") }} />
        </div>
      );
    }

    return (
      <TextInput
        {...common}
        onChange={(event) => update(field.name, event.target.value as T[keyof T])}
        placeholder={field.placeholder}
        type={field.type === "password" ? "password" : field.type === "url" ? "url" : "text"}
        value={String(rawValue ?? "")}
      />
    );
  };

  return (
    <>
      {group.description ? <p className="section__description">{group.description}</p> : null}
      <div className={formGridClassName(group, className)}>
        {group.fields.map((field) => {
          if (field.visibleWhen && !field.visibleWhen(value)) {
            return null;
          }
          const disabledReason = field.disabledWhen?.(value) ? resolveDisabledReason(field, value) : undefined;
          const fullWidth = field.span === "full" || field.type === "json" || field.type === "textarea";
          const rowClassName = ["field-row", fullWidth ? "field-row--full" : ""].filter(Boolean).join(" ");
          const descriptionId = `${String(field.name)}-description`;
          return (
            <label className={rowClassName} htmlFor={String(field.name)} key={String(field.name)}>
              <span className="field-row__label">
                <span className="field-row__label-text">{field.label}</span>
                {field.description ? (
                  <span className="field-row__tooltip">
                    <span aria-describedby={descriptionId} className="field-row__tooltip-trigger" tabIndex={0}>
                      <CircleHelp aria-hidden className="field-row__tooltip-icon" />
                    </span>
                    <span className="field-row__tooltip-bubble" id={descriptionId} role="tooltip">
                      {field.description}
                    </span>
                  </span>
                ) : null}
              </span>
              <span className="field-row__control">
                {renderField(field)}
                {errors[field.name] ? <span className="field-error">{errors[field.name]}</span> : null}
                {disabledReason ? <span className="field-row__help">{disabledReason}</span> : null}
              </span>
            </label>
          );
        })}
      </div>
    </>
  );
}

export function SchemaDrivenForm<T extends object>({
  collapsedGroupIds = [],
  disabled = false,
  errors = {},
  groups,
  onChange,
  value,
}: SchemaDrivenFormProps<T>) {
  return (
    <div className="settings-grid">
      {groups.map((group) => {
        const fields = (
          <SchemaFieldGrid disabled={disabled} errors={errors} group={group} onChange={onChange} value={value} />
        );

        if (collapsedGroupIds.includes(group.id)) {
          return (
            <details className="section schema-section" key={group.id}>
              <summary className="schema-section__summary">{group.title}</summary>
              {fields}
            </details>
          );
        }

        return (
          <section className="section schema-section" key={group.id}>
            <div className="section__header">
              <h2 className="section__title">{group.title}</h2>
            </div>
            {fields}
          </section>
        );
      })}
    </div>
  );
}

function JsonField({
  disabled,
  id,
  onChange,
  value,
}: {
  disabled: boolean;
  id: string;
  onChange: (value: unknown) => void;
  value: unknown;
}) {
  const [text, setText] = useState(() => formatJson(value));
  const [error, setError] = useState("");
  const { t } = useI18n();

  useEffect(() => {
    setText(formatJson(value));
  }, [value]);

  const handleCommit = () => {
    try {
      onChange(parseJson(text));
      setError("");
    } catch {
      setError(t("form.jsonInvalid"));
    }
  };

  return (
    <>
      <TextArea
        className={error ? "textarea--error" : ""}
        disabled={disabled}
        id={id}
        onBlur={handleCommit}
        onChange={(event) => setText(event.target.value)}
        spellCheck={false}
        value={text}
      />
      {error ? <div className="field-error">{error}</div> : null}
    </>
  );
}
