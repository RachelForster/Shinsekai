import { RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { ChatThemeManifest, ChatThemeTokens } from "../../../shared/theme/chatTheme";
import {
  chatThemeEditorSections,
  type ChatThemeEditorField,
  type ChatThemeEditorSection,
} from "../../../shared/theme/chatThemeSchema";
import { Button, IconButton, SegmentedTabs, Select, Switch, TextInput } from "../../../shared/ui";
import { ColorField } from "./ChatThemeCustomizerFields";

type EditorMode = "basic" | "advanced";

function valueAtPath(source: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, segment) => {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    return (current as Record<string, unknown>)[segment];
  }, source);
}

function FieldClearButton({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <IconButton className="chat-theme-customizer__field-clear" label={label} onClick={onClear}>
      <Trash2 aria-hidden className="icon-button__icon" />
    </IconButton>
  );
}

function ThemeField({
  field,
  onChange,
  value,
}: {
  field: ChatThemeEditorField;
  onChange: (path: string, value: unknown) => void;
  value: unknown;
}) {
  const { t } = useI18n();
  const label = t(field.labelKey);
  const clear = () => onChange(field.path, undefined);

  if (field.kind === "color") {
    return (
      <div className="chat-theme-customizer__field-with-action">
        <ColorField label={label} onChange={(next) => onChange(field.path, next)} value={String(value ?? "")} />
        {value !== undefined ? <FieldClearButton label={t("chat.theme.customizer.inherit")} onClear={clear} /> : null}
      </div>
    );
  }

  if (field.kind === "boolean") {
    return (
      <div className="chat-theme-customizer__field chat-theme-customizer__field--boolean">
        <span>{label}</span>
        <span className="chat-theme-customizer__inline-control">
          <Switch checked={value === true} onChange={(event) => onChange(field.path, event.target.checked)} />
          <span>{value === undefined ? t("chat.theme.customizer.inherited") : String(Boolean(value))}</span>
          {value !== undefined ? <FieldClearButton label={t("chat.theme.customizer.inherit")} onClear={clear} /> : null}
        </span>
      </div>
    );
  }

  if (field.kind === "select") {
    return (
      <label className="chat-theme-customizer__field">
        <span>{label}</span>
        <span className="chat-theme-customizer__inline-control">
          <Select
            onChange={(event) => onChange(field.path, event.target.value || undefined)}
            value={String(value ?? "")}
          >
            <option value="">{t("chat.theme.customizer.inherit")}</option>
            {field.options?.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </span>
      </label>
    );
  }

  if (field.kind === "number") {
    return (
      <label className="chat-theme-customizer__field">
        <span>{label}</span>
        <span className="chat-theme-customizer__inline-control">
          <TextInput
            max={field.max}
            min={field.min}
            onChange={(event) =>
              onChange(field.path, event.target.value === "" ? undefined : Number(event.target.value))
            }
            step={field.step ?? 1}
            type="number"
            value={typeof value === "number" ? value : ""}
          />
          {field.suffix ? <span className="chat-theme-customizer__suffix">{field.suffix}</span> : null}
          {value !== undefined ? <FieldClearButton label={t("chat.theme.customizer.inherit")} onClear={clear} /> : null}
        </span>
      </label>
    );
  }

  return (
    <label className="chat-theme-customizer__field">
      <span>{label}</span>
      <span className="chat-theme-customizer__inline-control">
        <TextInput
          className={field.kind === "asset" ? "chat-theme-customizer__asset-input" : undefined}
          onChange={(event) => onChange(field.path, event.target.value || undefined)}
          placeholder={field.kind === "asset" ? t("chat.theme.customizer.assetPlaceholder") : undefined}
          value={String(value ?? "")}
        />
        {value !== undefined ? <FieldClearButton label={t("chat.theme.customizer.inherit")} onClear={clear} /> : null}
      </span>
    </label>
  );
}

function ThemeSection({
  mode,
  onPatchToken,
  onResetSection,
  section,
  tokens,
  topLevel = false,
}: {
  mode: EditorMode;
  onPatchToken: (path: string, value: unknown) => void;
  onResetSection: (path: string) => void;
  section: ChatThemeEditorSection;
  tokens: ChatThemeTokens;
  topLevel?: boolean;
}) {
  const { t } = useI18n();
  if (section.advanced && mode !== "advanced") {
    return null;
  }
  const fields = (section.fields ?? []).filter((field) => mode === "advanced" || !field.advanced);
  const children = section.sections ?? [];

  return (
    <details
      className={topLevel ? undefined : "chat-theme-customizer__subsection"}
      open={topLevel && section.id === "global"}
    >
      <summary>
        <span>{t(section.labelKey)}</span>
        <Button
          className="chat-theme-customizer__section-reset"
          icon={<RotateCcw aria-hidden className="button__icon" />}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onResetSection(section.path);
          }}
          variant="ghost"
        >
          {t("chat.theme.customizer.resetSection")}
        </Button>
      </summary>
      {fields.length ? (
        <div className="chat-theme-customizer__field-grid">
          {fields.map((field) => (
            <ThemeField
              field={field}
              key={field.path}
              onChange={onPatchToken}
              value={valueAtPath(tokens, field.path)}
            />
          ))}
        </div>
      ) : null}
      {children.length ? (
        <div className="chat-theme-customizer__subsections">
          {children.map((child) => (
            <ThemeSection
              key={child.id}
              mode={mode}
              onPatchToken={onPatchToken}
              onResetSection={onResetSection}
              section={child}
              tokens={tokens}
            />
          ))}
        </div>
      ) : null}
    </details>
  );
}

function FontsEditor({
  draft,
  mode,
  onPatchToken,
  onResetSection,
}: {
  draft: ChatThemeManifest;
  mode: EditorMode;
  onPatchToken: (path: string, value: unknown) => void;
  onResetSection: (path: string) => void;
}) {
  const { t } = useI18n();
  if (mode !== "advanced") {
    return null;
  }
  const fonts = draft.tokens.fonts ?? [];
  return (
    <details>
      <summary>
        <span>{t("chat.theme.customizer.sectionFonts")}</span>
        <Button
          className="chat-theme-customizer__section-reset"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onResetSection("fonts");
          }}
          variant="ghost"
        >
          {t("chat.theme.customizer.resetSection")}
        </Button>
      </summary>
      <div className="chat-theme-customizer__font-list">
        {fonts.map((font, index) => (
          <div className="chat-theme-customizer__font-row" key={`${font.family}-${index}`}>
            <TextInput
              aria-label={t("chat.theme.customizer.fontFamily")}
              onChange={(event) => {
                const next = fonts.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, family: event.target.value } : item,
                );
                onPatchToken("fonts", next);
              }}
              placeholder={t("chat.theme.customizer.fontFamily")}
              value={font.family}
            />
            <TextInput
              aria-label={t("chat.theme.customizer.fontSource")}
              onChange={(event) => {
                const next = fonts.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, src: event.target.value } : item,
                );
                onPatchToken("fonts", next);
              }}
              placeholder={t("chat.theme.customizer.fontSource")}
              value={font.src}
            />
            <TextInput
              aria-label={t("chat.theme.customizer.fontWeight")}
              onChange={(event) => {
                const next = fonts.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, weight: event.target.value || undefined } : item,
                );
                onPatchToken("fonts", next);
              }}
              placeholder="400 / 400 800"
              value={font.weight ?? ""}
            />
            <IconButton
              label={t("common.delete")}
              onClick={() =>
                onPatchToken(
                  "fonts",
                  fonts.filter((_, itemIndex) => itemIndex !== index),
                )
              }
            >
              <Trash2 aria-hidden className="icon-button__icon" />
            </IconButton>
          </div>
        ))}
        <Button
          onClick={() => onPatchToken("fonts", [...fonts, { family: "", src: "assets/font.woff2" }])}
          variant="ghost"
        >
          {t("chat.theme.customizer.addFont")}
        </Button>
      </div>
    </details>
  );
}

export function ChatThemeEditor({
  draft,
  duplicateId,
  idError,
  isNewTheme,
  nameError,
  onPatchManifest,
  onPatchToken,
  onResetSection,
}: {
  draft: ChatThemeManifest;
  duplicateId: boolean;
  idError: string;
  isNewTheme: boolean;
  nameError: string;
  onPatchManifest: (patch: Partial<ChatThemeManifest>) => void;
  onPatchToken: (path: string, value: unknown) => void;
  onResetSection: (path: string) => void;
}) {
  const { language, t } = useI18n();
  const [mode, setMode] = useState<EditorMode>("basic");

  return (
    <div className="chat-theme-customizer__editor">
      <div className="chat-theme-customizer__editor-mode">
        <SegmentedTabs
          ariaLabel={t("chat.theme.customizer.editorMode")}
          items={[
            { id: "basic", label: t("chat.theme.customizer.modeBasic") },
            { id: "advanced", label: t("chat.theme.customizer.modeAdvanced") },
          ]}
          onChange={setMode}
          value={mode}
          variant="pills"
        />
        <span>
          {t(mode === "basic" ? "chat.theme.customizer.modeBasicHint" : "chat.theme.customizer.modeAdvancedHint")}
        </span>
      </div>

      <details open>
        <summary>{t("chat.theme.customizer.sectionMetadata")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.themeId")}</span>
            <TextInput
              aria-invalid={Boolean(idError || duplicateId)}
              disabled={!isNewTheme}
              onChange={(event) => onPatchManifest({ id: event.target.value.trim().toLowerCase() })}
              value={draft.id}
            />
            {idError || duplicateId ? (
              <small className="field-error">{duplicateId ? t("chat.theme.customizer.idDuplicate") : idError}</small>
            ) : null}
          </label>
          <label className="chat-theme-customizer__field">
            <span>{t("common.name")}</span>
            <TextInput
              aria-invalid={Boolean(nameError)}
              onChange={(event) => onPatchManifest({ name: { ...draft.name, [language]: event.target.value } })}
              value={draft.name[language] ?? draft.name.zh_CN ?? draft.name.en ?? ""}
            />
            {nameError ? <small className="field-error">{nameError}</small> : null}
          </label>
          <label className="chat-theme-customizer__field">
            <span>{t("common.author")}</span>
            <TextInput
              onChange={(event) => onPatchManifest({ author: event.target.value })}
              value={draft.author ?? ""}
            />
          </label>
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.version")}</span>
            <TextInput
              onChange={(event) => onPatchManifest({ version: event.target.value })}
              value={draft.version ?? ""}
            />
          </label>
        </div>
      </details>

      {chatThemeEditorSections.map((section) => (
        <ThemeSection
          key={section.id}
          mode={mode}
          onPatchToken={onPatchToken}
          onResetSection={onResetSection}
          section={section}
          tokens={draft.tokens}
          topLevel
        />
      ))}
      <FontsEditor draft={draft} mode={mode} onPatchToken={onPatchToken} onResetSection={onResetSection} />
    </div>
  );
}
