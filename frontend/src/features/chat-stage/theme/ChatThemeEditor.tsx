import { useI18n } from "../../../shared/i18n";
import type { ChatThemeManifest, ChatThemeTokens } from "../../../shared/theme/chatTheme";
import { TextInput } from "../../../shared/ui";
import { ColorField, RangeField, SelectField } from "./ChatThemeCustomizerFields";
import type { EditableThemeBlock } from "./useChatThemeCustomizer";

interface ChatThemeEditorProps {
  draft: ChatThemeManifest;
  duplicateId: boolean;
  idError: string;
  isNewTheme: boolean;
  nameError: string;
  onPatchBlock: (block: EditableThemeBlock, patch: Record<string, unknown>) => void;
  onPatchGlobal: (patch: NonNullable<ChatThemeTokens["global"]>) => void;
  onPatchManifest: (patch: Partial<ChatThemeManifest>) => void;
  onPatchTypewriter: (patch: NonNullable<ChatThemeTokens["typewriter"]>) => void;
}

export function ChatThemeEditor({
  draft,
  duplicateId,
  idError,
  isNewTheme,
  nameError,
  onPatchBlock,
  onPatchGlobal,
  onPatchManifest,
  onPatchTypewriter,
}: ChatThemeEditorProps) {
  const { language, t } = useI18n();
  const dialog = draft.tokens.dialog ?? {};
  const name = draft.tokens.name ?? {};
  const input = draft.tokens.input ?? {};
  const options = draft.tokens.options ?? {};
  const global = draft.tokens.global ?? {};

  return (
    <div className="chat-theme-customizer__editor">
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

      <details open>
        <summary>{t("chat.theme.customizer.sectionGlobal")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <ColorField
            fallback="#d4788e"
            label={t("chat.theme.customizer.themeColor")}
            onChange={(themeColor) => onPatchGlobal({ themeColor })}
            value={global.themeColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.fontFamily")}</span>
            <TextInput
              onChange={(event) => onPatchGlobal({ fontFamily: event.target.value })}
              value={global.fontFamily ?? ""}
            />
          </label>
        </div>
      </details>

      <details open>
        <summary>{t("chat.theme.customizer.sectionDialog")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <ColorField
            label={t("chat.theme.customizer.background")}
            onChange={(background) => onPatchBlock("dialog", { background })}
            value={dialog.background}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchBlock("dialog", { color })}
            value={dialog.color}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchBlock("dialog", { borderColor })}
            value={dialog.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchBlock("dialog", { borderRadius: event.target.value })}
              value={dialog.borderRadius ?? ""}
            />
          </label>
          <SelectField
            label={t("chat.theme.customizer.chrome")}
            onChange={(chrome) => onPatchBlock("dialog", { chrome })}
            value={dialog.chrome ?? "panel"}
          >
            <option value="panel">Panel</option>
            <option value="none">None</option>
          </SelectField>
          <SelectField
            label={t("chat.theme.customizer.align")}
            onChange={(textAlign) => onPatchBlock("dialog", { textAlign })}
            value={dialog.textAlign ?? "left"}
          >
            <option value="left">Left</option>
            <option value="center">Center</option>
          </SelectField>
          <RangeField
            label={t("chat.theme.customizer.width")}
            max={100}
            min={30}
            onChange={(widthPct) => onPatchBlock("dialog", { widthPct })}
            suffix="%"
            value={dialog.widthPct ?? 86}
          />
          <RangeField
            label={t("chat.theme.customizer.height")}
            max={260}
            min={96}
            onChange={(heightPx) => onPatchBlock("dialog", { heightPx })}
            suffix="px"
            value={dialog.heightPx ?? 156}
          />
          <RangeField
            label={t("chat.theme.customizer.padding")}
            max={72}
            min={8}
            onChange={(padding) => onPatchBlock("dialog", { padding })}
            suffix="px"
            value={dialog.padding ?? 20}
          />
          <RangeField
            label={t("chat.theme.customizer.fontSize")}
            max={64}
            min={12}
            onChange={(textSizePx) => onPatchBlock("dialog", { textSizePx })}
            suffix="px"
            value={dialog.textSizePx ?? 17}
          />
          <RangeField
            label={t("chat.theme.customizer.fontWeight")}
            max={900}
            min={300}
            onChange={(textWeight) => onPatchBlock("dialog", { textWeight })}
            step={100}
            value={dialog.textWeight ?? 400}
          />
          <RangeField
            label={t("chat.theme.customizer.offsetY")}
            max={240}
            min={-240}
            onChange={(offsetY) => onPatchBlock("dialog", { offsetY })}
            suffix="px"
            value={dialog.offsetY ?? 0}
          />
        </div>
      </details>

      <details>
        <summary>{t("chat.theme.customizer.sectionName")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <ColorField
            label={t("chat.theme.customizer.background")}
            onChange={(background) => onPatchBlock("name", { background })}
            value={name.background}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchBlock("name", { color })}
            value={name.color}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchBlock("name", { borderColor })}
            value={name.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchBlock("name", { borderRadius: event.target.value })}
              value={name.borderRadius ?? ""}
            />
          </label>
          <SelectField
            label={t("chat.theme.customizer.align")}
            onChange={(align) => onPatchBlock("name", { align })}
            value={name.align ?? "left"}
          >
            <option value="left">Left</option>
            <option value="center">Center</option>
          </SelectField>
          <SelectField
            label={t("chat.theme.customizer.decoration")}
            onChange={(decoration) => onPatchBlock("name", { decoration })}
            value={name.decoration ?? "accent"}
          >
            <option value="accent">Accent</option>
            <option value="line-dots">Line dots</option>
          </SelectField>
          <RangeField
            label={t("chat.theme.customizer.overlap")}
            max={48}
            min={0}
            onChange={(overlapPx) => onPatchBlock("name", { overlapPx })}
            suffix="px"
            value={name.overlapPx ?? 1}
          />
          <RangeField
            label={t("chat.theme.customizer.fontSize")}
            max={64}
            min={12}
            onChange={(textSizePx) => onPatchBlock("name", { textSizePx })}
            suffix="px"
            value={name.textSizePx ?? 15}
          />
          <RangeField
            label={t("chat.theme.customizer.fontWeight")}
            max={900}
            min={300}
            onChange={(textWeight) => onPatchBlock("name", { textWeight })}
            step={100}
            value={name.textWeight ?? 800}
          />
        </div>
      </details>

      <details>
        <summary>{t("chat.theme.customizer.sectionInput")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <SelectField
            label={t("chat.theme.customizer.layout")}
            onChange={(layout) => onPatchBlock("input", { layout })}
            value={input.layout ?? "default"}
          >
            <option value="default">Default</option>
            <option value="pill">Pill</option>
          </SelectField>
          <ColorField
            label={t("chat.theme.customizer.background")}
            onChange={(background) => onPatchBlock("input", { background })}
            value={input.background}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchBlock("input", { color })}
            value={input.color}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchBlock("input", { borderColor })}
            value={input.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchBlock("input", { borderRadius: event.target.value })}
              value={input.borderRadius ?? ""}
            />
          </label>
          <RangeField
            label={t("chat.theme.customizer.maxWidth")}
            max={900}
            min={320}
            onChange={(maxWidthPx) => onPatchBlock("input", { maxWidthPx })}
            suffix="px"
            value={input.maxWidthPx ?? 720}
          />
        </div>
      </details>

      <details>
        <summary>{t("chat.theme.customizer.sectionOptions")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <SelectField
            label={t("chat.theme.customizer.placement")}
            onChange={(placement) => onPatchBlock("options", { placement })}
            value={options.placement ?? "center"}
          >
            <option value="center">Center</option>
            <option value="right">Right</option>
          </SelectField>
          <SelectField
            label={t("chat.theme.customizer.widthMode")}
            onChange={(widthMode) => onPatchBlock("options", { widthMode })}
            value={options.widthMode ?? "fixed"}
          >
            <option value="fixed">Fixed</option>
            <option value="content">Content</option>
          </SelectField>
          <ColorField
            label={t("chat.theme.customizer.background")}
            onChange={(background) => onPatchBlock("options", { background })}
            value={options.background}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchBlock("options", { color })}
            value={options.color}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchBlock("options", { borderColor })}
            value={options.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchBlock("options", { borderRadius: event.target.value })}
              value={options.borderRadius ?? ""}
            />
          </label>
          <RangeField
            label={t("chat.theme.customizer.gap")}
            max={36}
            min={0}
            onChange={(gap) => onPatchBlock("options", { gap })}
            suffix="px"
            value={options.gap ?? 10}
          />
          <RangeField
            label={t("chat.theme.customizer.fontSize")}
            max={64}
            min={12}
            onChange={(textSizePx) => onPatchBlock("options", { textSizePx })}
            suffix="px"
            value={options.textSizePx ?? 18}
          />
          <RangeField
            label={t("chat.theme.customizer.fontWeight")}
            max={900}
            min={300}
            onChange={(textWeight) => onPatchBlock("options", { textWeight })}
            step={100}
            value={options.textWeight ?? 600}
          />
        </div>
      </details>

      <details>
        <summary>{t("chat.theme.customizer.sectionTypewriter")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <RangeField
            label={t("chat.theme.customizer.typewriterSpeed")}
            max={200}
            min={1}
            onChange={(cps) => onPatchTypewriter({ cps })}
            suffix=" cps"
            value={draft.tokens.typewriter?.cps ?? 40}
          />
        </div>
      </details>
    </div>
  );
}
