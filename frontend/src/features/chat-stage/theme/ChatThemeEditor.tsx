import { FileAudio, FileImage, RotateCcw, Trash2, Type, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { ChatThemeAsset, ChatThemeManifest, ChatThemeTokens } from "../../../shared/theme/chatTheme";
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

function assetAccept(path: string) {
  if (path === "typewriter.sound") {
    return ".wav,.mp3,.ogg,audio/*";
  }
  if (path === "fonts") {
    return ".woff,.woff2,.ttf,.otf,font/*";
  }
  return ".png,.jpg,.jpeg,.gif,.webp,.svg,image/*";
}

function AssetUploadButton({
  disabled,
  onUpload,
  path,
}: {
  disabled: boolean;
  onUpload: (file: File) => Promise<ChatThemeAsset>;
  path: string;
}) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  return (
    <>
      <input
        accept={assetAccept(path)}
        className="chat-theme-customizer__asset-file-input"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) {
            return;
          }
          setUploading(true);
          void onUpload(file)
            .catch(() => undefined)
            .finally(() => {
              setUploading(false);
              if (inputRef.current) {
                inputRef.current.value = "";
              }
            });
        }}
        ref={inputRef}
        type="file"
      />
      <IconButton
        disabled={disabled || uploading}
        label={t(disabled ? "chat.theme.customizer.assetSaveFirst" : "chat.theme.customizer.assetUpload")}
        onClick={() => inputRef.current?.click()}
      >
        <Upload aria-hidden className="icon-button__icon" />
      </IconButton>
    </>
  );
}

function ThemeField({
  canManageAssets,
  field,
  onChange,
  onUploadAsset,
  value,
}: {
  canManageAssets: boolean;
  field: ChatThemeEditorField;
  onChange: (path: string, value: unknown) => void;
  onUploadAsset: (file: File) => Promise<ChatThemeAsset>;
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

  if (field.kind === "asset") {
    return (
      <label className="chat-theme-customizer__field">
        <span>{label}</span>
        <span className="chat-theme-customizer__inline-control">
          <TextInput
            className="chat-theme-customizer__asset-input"
            onChange={(event) => onChange(field.path, event.target.value || undefined)}
            placeholder={t("chat.theme.customizer.assetPlaceholder")}
            value={String(value ?? "")}
          />
          <AssetUploadButton
            disabled={!canManageAssets}
            onUpload={async (file) => {
              const asset = await onUploadAsset(file);
              onChange(field.path, asset.path);
              return asset;
            }}
            path={field.path}
          />
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
          onChange={(event) => onChange(field.path, event.target.value || undefined)}
          value={String(value ?? "")}
        />
        {value !== undefined ? <FieldClearButton label={t("chat.theme.customizer.inherit")} onClear={clear} /> : null}
      </span>
    </label>
  );
}

function ThemeSection({
  canManageAssets,
  mode,
  onPatchToken,
  onResetSection,
  onUploadAsset,
  section,
  tokens,
  topLevel = false,
}: {
  canManageAssets: boolean;
  mode: EditorMode;
  onPatchToken: (path: string, value: unknown) => void;
  onResetSection: (path: string) => void;
  onUploadAsset: (file: File) => Promise<ChatThemeAsset>;
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
              canManageAssets={canManageAssets}
              field={field}
              key={field.path}
              onChange={onPatchToken}
              onUploadAsset={onUploadAsset}
              value={valueAtPath(tokens, field.path)}
            />
          ))}
        </div>
      ) : null}
      {children.length ? (
        <div className="chat-theme-customizer__subsections">
          {children.map((child) => (
            <ThemeSection
              canManageAssets={canManageAssets}
              key={child.id}
              mode={mode}
              onPatchToken={onPatchToken}
              onResetSection={onResetSection}
              onUploadAsset={onUploadAsset}
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
  canManageAssets,
  draft,
  mode,
  onPatchToken,
  onResetSection,
  onUploadAsset,
}: {
  canManageAssets: boolean;
  draft: ChatThemeManifest;
  mode: EditorMode;
  onPatchToken: (path: string, value: unknown) => void;
  onResetSection: (path: string) => void;
  onUploadAsset: (file: File) => Promise<ChatThemeAsset>;
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
            <AssetUploadButton
              disabled={!canManageAssets}
              onUpload={async (file) => {
                const asset = await onUploadAsset(file);
                const next = fonts.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, src: asset.path } : item,
                );
                onPatchToken("fonts", next);
                return asset;
              }}
              path="fonts"
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
  assets,
  assetsLoading,
  canManageAssets,
  draft,
  duplicateId,
  idError,
  isNewTheme,
  nameError,
  onPatchManifest,
  onPatchToken,
  onResetSection,
  onDeleteAsset,
  onUploadAsset,
}: {
  assets: ChatThemeAsset[];
  assetsLoading: boolean;
  canManageAssets: boolean;
  draft: ChatThemeManifest;
  duplicateId: boolean;
  idError: string;
  isNewTheme: boolean;
  nameError: string;
  onPatchManifest: (patch: Partial<ChatThemeManifest>) => void;
  onPatchToken: (path: string, value: unknown) => void;
  onResetSection: (path: string) => void;
  onDeleteAsset: (path: string) => void;
  onUploadAsset: (file: File) => Promise<ChatThemeAsset>;
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
          canManageAssets={canManageAssets}
          key={section.id}
          mode={mode}
          onPatchToken={onPatchToken}
          onResetSection={onResetSection}
          onUploadAsset={onUploadAsset}
          section={section}
          tokens={draft.tokens}
          topLevel
        />
      ))}
      <FontsEditor
        canManageAssets={canManageAssets}
        draft={draft}
        mode={mode}
        onPatchToken={onPatchToken}
        onResetSection={onResetSection}
        onUploadAsset={onUploadAsset}
      />
      {mode === "advanced" ? (
        <details>
          <summary>{t("chat.theme.customizer.sectionAssets")}</summary>
          <div className="chat-theme-customizer__asset-workbench">
            {!canManageAssets ? <p>{t("chat.theme.customizer.assetSaveFirst")}</p> : null}
            {assetsLoading ? <p>{t("chat.theme.customizer.assetsLoading")}</p> : null}
            {canManageAssets && !assetsLoading && !assets.length ? (
              <p>{t("chat.theme.customizer.assetsEmpty")}</p>
            ) : null}
            {assets.map((asset) => (
              <div className="chat-theme-customizer__asset-row" key={asset.path}>
                {asset.kind === "audio" ? (
                  <FileAudio aria-hidden />
                ) : asset.kind === "font" ? (
                  <Type aria-hidden />
                ) : (
                  <FileImage aria-hidden />
                )}
                <span>
                  <strong>{asset.name}</strong>
                  <small>{asset.path}</small>
                </span>
                <small>{Math.max(1, Math.round(asset.size / 1024))} KiB</small>
                <IconButton label={t("common.delete")} onClick={() => onDeleteAsset(asset.path)}>
                  <Trash2 aria-hidden className="icon-button__icon" />
                </IconButton>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
