import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";

import type { FormFieldSchema, FormGroupSchema } from "../entities/config/types";
import type { SchemaErrorMap } from "../entities/config/schema";
import { useI18n } from "../shared/i18n";
import { ColorInput, FilePicker, NumberInput, Select, TextArea, TextInput } from "../shared/ui";

interface SchemaDrivenFormProps<T extends object> {
  collapsedGroupIds?: string[];
  disabled?: boolean;
  errors?: SchemaErrorMap<T>;
  groups: Array<FormGroupSchema<T>>;
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

export function SchemaDrivenForm<T extends object>({
  collapsedGroupIds = [],
  disabled = false,
  errors = {},
  groups,
  onChange,
  value,
}: SchemaDrivenFormProps<T>) {
  const { t } = useI18n();

  const update = <K extends keyof T>(name: K, next: T[K]) => {
    onChange({ ...value, [name]: next });
  };

  const renderField = (field: FormFieldSchema<T>) => {
    const rawValue = value[field.name];
    const common = {
      disabled,
      id: String(field.name),
    };

    if (field.type === "checkbox") {
      return (
        <input
          {...common}
          checked={Boolean(rawValue)}
          onChange={(event) => update(field.name, event.target.checked as T[keyof T])}
          type="checkbox"
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
          disabled={disabled}
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
      return (
        <NumberInput
          {...common}
          max={field.max}
          min={field.min}
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
    <div className="settings-grid">
      {groups.map((group) => {
        const fields = (
          <>
            {group.description ? <p className="section__description">{group.description}</p> : null}
            <div className="form-grid form-grid--two">
              {group.fields.map((field) =>
                field.visibleWhen && !field.visibleWhen(value) ? null : (
                  <label className="field-row" htmlFor={String(field.name)} key={String(field.name)}>
                    <span className="field-row__label">{field.label}</span>
                    <span className="field-row__control">
                      {renderField(field)}
                      {errors[field.name] ? <span className="field-error">{errors[field.name]}</span> : null}
                      {field.description ? <span className="field-row__help">{field.description}</span> : null}
                    </span>
                  </label>
                ),
              )}
            </div>
          </>
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
