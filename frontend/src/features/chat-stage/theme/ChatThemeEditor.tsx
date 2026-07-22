import { useI18n } from "../../../shared/i18n";
import type {
  BackgroundLayer,
  ChatThemeManifest,
  ChatThemeTokens,
  TextLayer,
  VisualBlock,
} from "../../../shared/theme/chatTheme";
import { TextInput } from "../../../shared/ui";
import { ColorField, RangeField, SelectField } from "./ChatThemeCustomizerFields";
import type { EditableThemeBlock, EditableThemeLayer } from "./useChatThemeCustomizer";

function resolvedBackgroundLayer(block: VisualBlock): BackgroundLayer {
  return {
    background: block.background,
    backgroundImage: block.backgroundImage,
    borderColor: block.borderColor,
    borderRadius: block.borderRadius,
    boxShadow: block.boxShadow,
    ...block.backgroundLayer,
  };
}

function resolvedTextLayer(block: VisualBlock): TextLayer {
  return { color: block.color, ...block.textLayer };
}

interface ChatThemeEditorProps {
  draft: ChatThemeManifest;
  duplicateId: boolean;
  idError: string;
  isNewTheme: boolean;
  nameError: string;
  onPatchBlock: (block: EditableThemeBlock, patch: Record<string, unknown>) => void;
  onPatchGlobal: (patch: NonNullable<ChatThemeTokens["global"]>) => void;
  onPatchLayer: (block: EditableThemeBlock, layer: EditableThemeLayer, patch: Record<string, unknown>) => void;
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
  onPatchLayer,
  onPatchManifest,
  onPatchTypewriter,
}: ChatThemeEditorProps) {
  const { language, t } = useI18n();
  const dialog = draft.tokens.dialog ?? {};
  const name = draft.tokens.name ?? {};
  const input = draft.tokens.input ?? {};
  const options = draft.tokens.options ?? {};
  const toolbar = draft.tokens.toolbar ?? {};
  const send = draft.tokens.send ?? {};
  const global = draft.tokens.global ?? {};
  const dialogBackground = resolvedBackgroundLayer(dialog);
  const dialogText: TextLayer = {
    color: dialog.color,
    textAlign: dialog.textAlign,
    textShadow: dialog.textShadow,
    textSizePx: dialog.textSizePx,
    textWeight: dialog.textWeight,
    ...dialog.textLayer,
  };
  const nameBackground = resolvedBackgroundLayer(name);
  const nameText: TextLayer = {
    color: name.color,
    fontFamily: name.fontFamily,
    textShadow: name.textShadow,
    textSizePx: name.textSizePx,
    textWeight: name.textWeight,
    ...name.textLayer,
  };
  const inputBackground = resolvedBackgroundLayer(input);
  const inputText = resolvedTextLayer(input);
  const optionBackground = resolvedBackgroundLayer(options);
  const optionText: TextLayer = {
    color: options.color,
    textShadow: options.textShadow,
    textSizePx: options.textSizePx,
    textSizeVh: options.textSizeVh,
    textWeight: options.textWeight,
    ...options.textLayer,
  };
  const toolbarBackground = resolvedBackgroundLayer(toolbar);
  const toolbarText = resolvedTextLayer(toolbar);
  const sendBackground = resolvedBackgroundLayer(send);
  const sendText = resolvedTextLayer(send);

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
            onChange={(background) => onPatchLayer("dialog", "backgroundLayer", { background })}
            value={dialogBackground.background}
          />
          <RangeField
            label={t("chat.theme.customizer.backgroundOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("dialog", "backgroundLayer", { opacity })}
            step={0.05}
            value={dialogBackground.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchLayer("dialog", "textLayer", { color })}
            value={dialogText.color}
          />
          <RangeField
            label={t("chat.theme.customizer.textOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("dialog", "textLayer", { opacity })}
            step={0.05}
            value={dialogText.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchLayer("dialog", "backgroundLayer", { borderColor })}
            value={dialogBackground.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchLayer("dialog", "backgroundLayer", { borderRadius: event.target.value })}
              value={dialogBackground.borderRadius ?? ""}
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
            onChange={(textAlign) => onPatchLayer("dialog", "textLayer", { textAlign })}
            value={dialogText.textAlign ?? "left"}
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
            onChange={(textSizePx) => onPatchLayer("dialog", "textLayer", { textSizePx })}
            suffix="px"
            value={dialogText.textSizePx ?? 17}
          />
          <RangeField
            label={t("chat.theme.customizer.fontWeight")}
            max={900}
            min={300}
            onChange={(textWeight) => onPatchLayer("dialog", "textLayer", { textWeight })}
            step={100}
            value={dialogText.textWeight ?? 400}
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
            onChange={(background) => onPatchLayer("name", "backgroundLayer", { background })}
            value={nameBackground.background}
          />
          <RangeField
            label={t("chat.theme.customizer.backgroundOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("name", "backgroundLayer", { opacity })}
            step={0.05}
            value={nameBackground.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchLayer("name", "textLayer", { color })}
            value={nameText.color}
          />
          <RangeField
            label={t("chat.theme.customizer.textOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("name", "textLayer", { opacity })}
            step={0.05}
            value={nameText.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchLayer("name", "backgroundLayer", { borderColor })}
            value={nameBackground.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchLayer("name", "backgroundLayer", { borderRadius: event.target.value })}
              value={nameBackground.borderRadius ?? ""}
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
            <option value="arrow-fade">Arrow fade</option>
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
            onChange={(textSizePx) => onPatchLayer("name", "textLayer", { textSizePx })}
            suffix="px"
            value={nameText.textSizePx ?? 15}
          />
          <RangeField
            label={t("chat.theme.customizer.fontWeight")}
            max={900}
            min={300}
            onChange={(textWeight) => onPatchLayer("name", "textLayer", { textWeight })}
            step={100}
            value={nameText.textWeight ?? 800}
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
            onChange={(background) => onPatchLayer("input", "backgroundLayer", { background })}
            value={inputBackground.background}
          />
          <RangeField
            label={t("chat.theme.customizer.backgroundOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("input", "backgroundLayer", { opacity })}
            step={0.05}
            value={inputBackground.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchLayer("input", "textLayer", { color })}
            value={inputText.color}
          />
          <RangeField
            label={t("chat.theme.customizer.textOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("input", "textLayer", { opacity })}
            step={0.05}
            value={inputText.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchLayer("input", "backgroundLayer", { borderColor })}
            value={inputBackground.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchLayer("input", "backgroundLayer", { borderRadius: event.target.value })}
              value={inputBackground.borderRadius ?? ""}
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
            onChange={(background) => onPatchLayer("options", "backgroundLayer", { background })}
            value={optionBackground.background}
          />
          <RangeField
            label={t("chat.theme.customizer.backgroundOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("options", "backgroundLayer", { opacity })}
            step={0.05}
            value={optionBackground.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchLayer("options", "textLayer", { color })}
            value={optionText.color}
          />
          <RangeField
            label={t("chat.theme.customizer.textOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("options", "textLayer", { opacity })}
            step={0.05}
            value={optionText.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchLayer("options", "backgroundLayer", { borderColor })}
            value={optionBackground.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchLayer("options", "backgroundLayer", { borderRadius: event.target.value })}
              value={optionBackground.borderRadius ?? ""}
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
            onChange={(textSizePx) => onPatchLayer("options", "textLayer", { textSizePx })}
            suffix="px"
            value={optionText.textSizePx ?? 18}
          />
          <RangeField
            label={t("chat.theme.customizer.fontWeight")}
            max={900}
            min={300}
            onChange={(textWeight) => onPatchLayer("options", "textLayer", { textWeight })}
            step={100}
            value={optionText.textWeight ?? 600}
          />
        </div>
      </details>

      <details>
        <summary>{t("chat.theme.customizer.sectionToolbar")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <ColorField
            label={t("chat.theme.customizer.background")}
            onChange={(background) => onPatchLayer("toolbar", "backgroundLayer", { background })}
            value={toolbarBackground.background}
          />
          <RangeField
            label={t("chat.theme.customizer.backgroundOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("toolbar", "backgroundLayer", { opacity })}
            step={0.05}
            value={toolbarBackground.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchLayer("toolbar", "textLayer", { color })}
            value={toolbarText.color}
          />
          <RangeField
            label={t("chat.theme.customizer.textOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("toolbar", "textLayer", { opacity })}
            step={0.05}
            value={toolbarText.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchLayer("toolbar", "backgroundLayer", { borderColor })}
            value={toolbarBackground.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchLayer("toolbar", "backgroundLayer", { borderRadius: event.target.value })}
              value={toolbarBackground.borderRadius ?? ""}
            />
          </label>
        </div>
      </details>

      <details>
        <summary>{t("chat.theme.customizer.sectionSend")}</summary>
        <div className="chat-theme-customizer__field-grid">
          <ColorField
            label={t("chat.theme.customizer.background")}
            onChange={(background) => onPatchLayer("send", "backgroundLayer", { background })}
            value={sendBackground.background}
          />
          <RangeField
            label={t("chat.theme.customizer.backgroundOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("send", "backgroundLayer", { opacity })}
            step={0.05}
            value={sendBackground.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.textColor")}
            onChange={(color) => onPatchLayer("send", "textLayer", { color })}
            value={sendText.color}
          />
          <RangeField
            label={t("chat.theme.customizer.textOpacity")}
            max={1}
            min={0}
            onChange={(opacity) => onPatchLayer("send", "textLayer", { opacity })}
            step={0.05}
            value={sendText.opacity ?? 1}
          />
          <ColorField
            label={t("chat.theme.customizer.borderColor")}
            onChange={(borderColor) => onPatchLayer("send", "backgroundLayer", { borderColor })}
            value={sendBackground.borderColor}
          />
          <label className="chat-theme-customizer__field">
            <span>{t("chat.theme.customizer.borderRadius")}</span>
            <TextInput
              onChange={(event) => onPatchLayer("send", "backgroundLayer", { borderRadius: event.target.value })}
              value={sendBackground.borderRadius ?? ""}
            />
          </label>
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
