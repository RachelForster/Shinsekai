import { useId, type ChangeEvent } from "react";
import { Languages } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import type { ChatCommand } from "../../../shared/platform/types";
import { Select, Switch } from "../../../shared/ui";
import type { ChatStageSprite } from "../chatState";
import { ChatStageModal } from "./ChatStageModal";
import {
  clampRuntimeNumber,
  runtimeDialogOpacityMax,
  runtimeDialogOpacityMin,
  runtimeDialogOpacityStep,
  runtimeDialogScaleMax,
  runtimeDialogScaleMin,
  runtimeDialogScaleStep,
  runtimeDialogFontSizeMax,
  runtimeDialogFontSizeMin,
  runtimeNameFontSizeMax,
  runtimeNameFontSizeMin,
  runtimeSpriteDefaultScaleKey,
  runtimeSpriteKey,
  runtimeSpriteLabel,
  runtimeSpriteOffsetMax,
  runtimeSpriteOffsetMin,
  runtimeSpriteOffsetStep,
  runtimeSpriteScaleMax,
  runtimeSpriteScaleMin,
  runtimeSpriteScaleStep,
  runtimeTextSpeedMax,
  runtimeTextSpeedMin,
  runtimeWindowScaleMax,
  runtimeWindowScaleMin,
  runtimeWindowScaleStep,
  chatStageTextAlignments,
  chatStageDialogFillGradientDirections,
  chatStageDialogFillGradientModes,
  chatStageTextDirections,
  runtimeDialogFillOpacityMax,
  runtimeDialogFillOpacityMin,
  runtimeDialogFillOpacityStep,
  type ChatStageTextStyleConfig,
  type ChatStageTextStylePatch,
  type ChatStageTextStyleTarget,
  type ChatStageTextAlign,
  type ChatStageTextDirection,
  type ChatStageDialogFillConfig,
  type ChatStageDialogFillGradientDirection,
  type ChatStageDialogFillGradientMode,
  type ChatStageDialogFillPatch,
} from "../runtimeConfig";

const chatVoiceLanguages = [
  { labelKey: "system.asr.langJa", value: "ja" },
  { labelKey: "system.asr.langEn", value: "en" },
  { labelKey: "system.asr.langZh", value: "zh" },
  { labelKey: "system.asr.langYue", value: "yue" },
] as const;

const dialogTextDirectionOptions: Array<{
  labelKey: Parameters<ReturnType<typeof useI18n>["t"]>[0];
  value: ChatStageTextDirection;
}> = [
  { labelKey: "chat.config.textDirectionLtr", value: "ltr" },
  { labelKey: "chat.config.textDirectionRtl", value: "rtl" },
];

const dialogTextAlignOptions: Array<{
  labelKey: Parameters<ReturnType<typeof useI18n>["t"]>[0];
  value: ChatStageTextAlign;
}> = [
  { labelKey: "chat.config.dialogTextAlignCenter", value: "center" },
  { labelKey: "chat.config.dialogTextAlignLeft", value: "left" },
  { labelKey: "chat.config.dialogTextAlignRight", value: "right" },
  { labelKey: "chat.config.dialogTextAlignJustify", value: "justify" },
];

const dialogFillGradientModeOptions: Array<{
  labelKey: Parameters<ReturnType<typeof useI18n>["t"]>[0];
  value: ChatStageDialogFillGradientMode;
}> = [
  { labelKey: "chat.config.dialogFillGradientSingle", value: "single" },
  { labelKey: "chat.config.dialogFillGradientDual", value: "dual" },
];

const dialogFillGradientDirectionOptions: Array<{
  labelKey: Parameters<ReturnType<typeof useI18n>["t"]>[0];
  value: ChatStageDialogFillGradientDirection;
}> = [
  { labelKey: "chat.config.dialogFillGradientToBottom", value: "to-bottom" },
  { labelKey: "chat.config.dialogFillGradientToTop", value: "to-top" },
];

export function ChatConfigDialog({
  configThemeColor,
  configUseMainThemeColor,
  dialogOpacity,
  dialogFill,
  dialogScale,
  dialogText,
  effectiveDialogText,
  effectiveNameText,
  mainThemeColor,
  nameText,
  longPressTalk,
  longPressTalkAvailable,
  longPressTalkVisible = false,
  onConfigThemeColorChange,
  onConfigUseMainThemeColorChange,
  onClose,
  onCommand,
  onDialogOpacityChange,
  onDialogFillChange,
  onDialogScaleChange,
  onLongPressTalkChange,
  onSpriteOffsetXChange,
  onSpriteOffsetYChange,
  onSpriteScaleChange,
  onTextSpeedChange,
  onTextStyleChange,
  onWindowScaleChange,
  open,
  spriteOffsetX,
  spriteOffsetY,
  spriteScales,
  sprites,
  textSpeed,
  voiceLanguage,
  windowScale,
}: {
  configThemeColor: string;
  configUseMainThemeColor: boolean;
  dialogOpacity: number;
  dialogFill: ChatStageDialogFillConfig;
  dialogScale: number;
  dialogText: ChatStageTextStyleConfig;
  effectiveDialogText?: ChatStageTextStyleConfig;
  effectiveNameText?: ChatStageTextStyleConfig;
  mainThemeColor: string;
  nameText: ChatStageTextStyleConfig;
  longPressTalk: boolean;
  longPressTalkAvailable: boolean;
  longPressTalkVisible?: boolean;
  onConfigThemeColorChange: (value: string) => void;
  onConfigUseMainThemeColorChange: (value: boolean) => void;
  onClose: () => void;
  onCommand: (command: ChatCommand) => void;
  onDialogOpacityChange: (value: number) => void;
  onDialogFillChange: (patch: ChatStageDialogFillPatch) => void;
  onDialogScaleChange: (value: number) => void;
  onLongPressTalkChange: (value: boolean) => void;
  onSpriteOffsetXChange: (value: number) => void;
  onSpriteOffsetYChange: (value: number) => void;
  onSpriteScaleChange: (spriteKey: string, value: number) => void;
  onTextSpeedChange: (value: number) => void;
  onTextStyleChange: (target: ChatStageTextStyleTarget, patch: ChatStageTextStylePatch) => void;
  onWindowScaleChange: (value: number) => void;
  open: boolean;
  spriteOffsetX: number;
  spriteOffsetY: number;
  spriteScales: Record<string, number>;
  sprites: ChatStageSprite[];
  textSpeed: number;
  voiceLanguage: string;
  windowScale: number;
}) {
  const { t } = useI18n();
  const titleId = useId();
  const dialogTextView = effectiveDialogText ?? dialogText;
  const nameTextView = effectiveNameText ?? nameText;
  const dialogBoldChecked = dialogText.boldOverride === true ? dialogText.bold : dialogTextView.bold;
  const nameBoldChecked = nameText.boldOverride === true ? nameText.bold : nameTextView.bold;
  const configThemeColorView = configUseMainThemeColor ? mainThemeColor : configThemeColor;
  const dialogOpacityPercent = Math.round(dialogOpacity * 100);
  const dialogFillOpacityPercent = Math.round(dialogFill.opacity * 100);
  const dialogScalePercent = Math.round(dialogScale * 100);
  const windowScalePercent = Math.round(windowScale * 100);

  if (!open) {
    return null;
  }

  const handleTextSpeedChange = (event: ChangeEvent<HTMLInputElement>) => {
    onTextSpeedChange(
      Math.round(clampRuntimeNumber(event.target.value, textSpeed, runtimeTextSpeedMin, runtimeTextSpeedMax)),
    );
  };
  const handleDialogOpacityChange = (event: ChangeEvent<HTMLInputElement>) => {
    onDialogOpacityChange(
      clampRuntimeNumber(event.target.value, dialogOpacity, runtimeDialogOpacityMin, runtimeDialogOpacityMax),
    );
  };
  const handleDialogFillOpacityChange = (event: ChangeEvent<HTMLInputElement>) => {
    onDialogFillChange({
      opacity: clampRuntimeNumber(
        event.target.value,
        dialogFill.opacity,
        runtimeDialogFillOpacityMin,
        runtimeDialogFillOpacityMax,
      ),
    });
  };
  const handleDialogFillGradientModeChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value as ChatStageDialogFillGradientMode;
    if (chatStageDialogFillGradientModes.includes(value)) {
      onDialogFillChange({ gradientMode: value });
    }
  };
  const handleDialogFillGradientDirectionChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value as ChatStageDialogFillGradientDirection;
    if (chatStageDialogFillGradientDirections.includes(value)) {
      onDialogFillChange({ gradientDirection: value });
    }
  };
  const handleDialogScaleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onDialogScaleChange(
      clampRuntimeNumber(event.target.value, dialogScale, runtimeDialogScaleMin, runtimeDialogScaleMax),
    );
  };
  const handleSpriteOffsetXChange = (event: ChangeEvent<HTMLInputElement>) => {
    onSpriteOffsetXChange(
      Math.round(clampRuntimeNumber(event.target.value, spriteOffsetX, runtimeSpriteOffsetMin, runtimeSpriteOffsetMax)),
    );
  };
  const handleSpriteOffsetYChange = (event: ChangeEvent<HTMLInputElement>) => {
    onSpriteOffsetYChange(
      Math.round(clampRuntimeNumber(event.target.value, spriteOffsetY, runtimeSpriteOffsetMin, runtimeSpriteOffsetMax)),
    );
  };
  const handleWindowScaleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onWindowScaleChange(
      clampRuntimeNumber(event.target.value, windowScale, runtimeWindowScaleMin, runtimeWindowScaleMax),
    );
  };
  const handleTextStyleSizeChange =
    (target: ChatStageTextStyleTarget, current: number, min: number, max: number) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      onTextStyleChange(target, { fontSize: Math.round(clampRuntimeNumber(event.target.value, current, min, max)) });
    };
  const handleDialogTextDirectionChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value as ChatStageTextDirection;
    if (chatStageTextDirections.includes(value)) {
      onTextStyleChange("dialogText", { direction: value });
    }
  };
  const handleDialogTextAlignChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value as ChatStageTextAlign;
    if (chatStageTextAlignments.includes(value)) {
      onTextStyleChange("dialogText", { align: value });
    }
  };

  return (
    <ChatStageModal
      backdropClassName="chat-config-backdrop"
      closeLabel={t("common.close")}
      dialogClassName="chat-config-dialog"
      dialogId="chat-stage-dialog-config"
      labelledBy={titleId}
      onClose={onClose}
      open={open}
      title={t("chat.toolbar.config")}
    >
      <div className="chat-stage-modal__body chat-config-dialog__body">
        <section className="chat-config-dialog__section">
          <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionMenuAppearance")}</h3>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.menuThemeColor")}</span>
            <input
              aria-label={t("chat.config.menuThemeColor")}
              className="chat-config-dialog__color-input"
              disabled={configUseMainThemeColor}
              onChange={(event) => onConfigThemeColorChange(event.target.value)}
              type="color"
              value={configThemeColorView}
            />
          </label>
          <div className="chat-config-dialog__row chat-config-dialog__checkbox-row">
            <span className="chat-config-dialog__label">{t("chat.config.useMainThemeColor")}</span>
            <Switch
              aria-label={t("chat.config.useMainThemeColor")}
              checked={configUseMainThemeColor}
              className="chat-config-dialog__switch"
              onChange={(event) => onConfigUseMainThemeColorChange(event.target.checked)}
            />
          </div>
        </section>
        <section className="chat-config-dialog__section">
          <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionConversation")}</h3>
          <label className="chat-config-dialog__row chat-config-dialog__voice">
            <span className="chat-config-dialog__label">
              <Languages aria-hidden className="chat-config-dialog__voice-icon" />
              {t("template.field.voiceLanguage")}
            </span>
            <Select
              aria-label={t("template.field.voiceLanguage")}
              className="chat-config-dialog__voice-select"
              onChange={(event) => onCommand({ payload: event.target.value, type: "change-voice-language" })}
              value={voiceLanguage}
            >
              {chatVoiceLanguages.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </Select>
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.textSpeed")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.textSpeed")}
                className="chat-config-dialog__range"
                max={runtimeTextSpeedMax}
                min={runtimeTextSpeedMin}
                onChange={handleTextSpeedChange}
                step={1}
                type="range"
                value={textSpeed}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.textSpeedValue", { value: textSpeed })}
              </span>
            </span>
          </label>
          {longPressTalkVisible ? (
            <div className="chat-config-dialog__row chat-config-dialog__checkbox-row">
              <span className="chat-config-dialog__label">{t("chat.config.longPressTalk")}</span>
              <Switch
                aria-disabled={!longPressTalkAvailable && !longPressTalk}
                aria-label={t("chat.config.longPressTalk")}
                checked={longPressTalk && longPressTalkAvailable}
                className="chat-config-dialog__switch"
                onChange={(event) => onLongPressTalkChange(event.target.checked)}
              />
            </div>
          ) : null}
        </section>

        <section className="chat-config-dialog__section">
          <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionTypography")}</h3>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.nameFontFamily")}</span>
            <input
              className="chat-config-dialog__text-input"
              onChange={(event) => onTextStyleChange("nameText", { fontFamily: event.target.value })}
              placeholder={nameTextView.fontFamily || t("chat.config.fontFamilyPlaceholder")}
              value={nameText.fontFamily}
            />
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.nameFontSize")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.nameFontSize")}
                className="chat-config-dialog__range"
                max={runtimeNameFontSizeMax}
                min={runtimeNameFontSizeMin}
                onChange={handleTextStyleSizeChange(
                  "nameText",
                  nameTextView.fontSize,
                  runtimeNameFontSizeMin,
                  runtimeNameFontSizeMax,
                )}
                step={1}
                type="range"
                value={nameTextView.fontSize}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.fontSizeValue", { value: nameTextView.fontSize })}
              </span>
            </span>
          </label>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.nameColor")}</span>
            <input
              aria-label={t("chat.config.nameColor")}
              className="chat-config-dialog__color-input"
              onChange={(event) => onTextStyleChange("nameText", { color: event.target.value })}
              type="color"
              value={nameTextView.color}
            />
          </label>
          <div className="chat-config-dialog__row chat-config-dialog__checkbox-row">
            <span className="chat-config-dialog__label">{t("chat.config.nameBold")}</span>
            <Switch
              aria-label={t("chat.config.nameBold")}
              checked={nameBoldChecked}
              className="chat-config-dialog__switch"
              onChange={(event) => onTextStyleChange("nameText", { bold: event.target.checked, boldOverride: true })}
            />
          </div>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogFontFamily")}</span>
            <input
              className="chat-config-dialog__text-input"
              onChange={(event) => onTextStyleChange("dialogText", { fontFamily: event.target.value })}
              placeholder={dialogTextView.fontFamily || t("chat.config.fontFamilyPlaceholder")}
              value={dialogText.fontFamily}
            />
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogFontSize")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.dialogFontSize")}
                className="chat-config-dialog__range"
                max={runtimeDialogFontSizeMax}
                min={runtimeDialogFontSizeMin}
                onChange={handleTextStyleSizeChange(
                  "dialogText",
                  dialogTextView.fontSize,
                  runtimeDialogFontSizeMin,
                  runtimeDialogFontSizeMax,
                )}
                step={1}
                type="range"
                value={dialogTextView.fontSize}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.fontSizeValue", { value: dialogTextView.fontSize })}
              </span>
            </span>
          </label>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogTextDirection")}</span>
            <Select
              aria-label={t("chat.config.dialogTextDirection")}
              className="chat-config-dialog__select"
              onChange={handleDialogTextDirectionChange}
              value={dialogTextView.direction ?? "ltr"}
            >
              {dialogTextDirectionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </Select>
          </label>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogTextAlign")}</span>
            <Select
              aria-label={t("chat.config.dialogTextAlign")}
              className="chat-config-dialog__select"
              onChange={handleDialogTextAlignChange}
              value={dialogTextView.align ?? "center"}
            >
              {dialogTextAlignOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </option>
              ))}
            </Select>
          </label>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogColor")}</span>
            <input
              aria-label={t("chat.config.dialogColor")}
              className="chat-config-dialog__color-input"
              onChange={(event) => onTextStyleChange("dialogText", { color: event.target.value })}
              type="color"
              value={dialogTextView.color}
            />
          </label>
          <div className="chat-config-dialog__row chat-config-dialog__checkbox-row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogBold")}</span>
            <Switch
              aria-label={t("chat.config.dialogBold")}
              checked={dialogBoldChecked}
              className="chat-config-dialog__switch"
              onChange={(event) => onTextStyleChange("dialogText", { bold: event.target.checked, boldOverride: true })}
            />
          </div>
        </section>

        <section className="chat-config-dialog__section">
          <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionLayout")}</h3>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.windowScale")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.windowScale")}
                className="chat-config-dialog__range"
                max={runtimeWindowScaleMax}
                min={runtimeWindowScaleMin}
                onChange={handleWindowScaleChange}
                step={runtimeWindowScaleStep}
                type="range"
                value={windowScale}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.scaleValue", { value: windowScalePercent })}
              </span>
            </span>
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogScale")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.dialogScale")}
                className="chat-config-dialog__range"
                max={runtimeDialogScaleMax}
                min={runtimeDialogScaleMin}
                onChange={handleDialogScaleChange}
                step={runtimeDialogScaleStep}
                type="range"
                value={dialogScale}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.scaleValue", { value: dialogScalePercent })}
              </span>
            </span>
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogOpacity")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.dialogOpacity")}
                className="chat-config-dialog__range"
                max={runtimeDialogOpacityMax}
                min={runtimeDialogOpacityMin}
                onChange={handleDialogOpacityChange}
                step={runtimeDialogOpacityStep}
                type="range"
                value={dialogOpacity}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.dialogOpacityValue", { value: dialogOpacityPercent })}
              </span>
            </span>
          </label>
          <label className="chat-config-dialog__row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogFillColor")}</span>
            <input
              aria-label={t("chat.config.dialogFillColor")}
              className="chat-config-dialog__color-input"
              onChange={(event) => onDialogFillChange({ color: event.target.value })}
              type="color"
              value={dialogFill.color}
            />
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogFillOpacity")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.dialogFillOpacity")}
                className="chat-config-dialog__range"
                max={runtimeDialogFillOpacityMax}
                min={runtimeDialogFillOpacityMin}
                onChange={handleDialogFillOpacityChange}
                step={runtimeDialogFillOpacityStep}
                type="range"
                value={dialogFill.opacity}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.dialogOpacityValue", { value: dialogFillOpacityPercent })}
              </span>
            </span>
          </label>
          <div className="chat-config-dialog__row chat-config-dialog__checkbox-row">
            <span className="chat-config-dialog__label">{t("chat.config.dialogFillGradient")}</span>
            <Switch
              aria-label={t("chat.config.dialogFillGradient")}
              checked={dialogFill.gradient}
              className="chat-config-dialog__switch"
              onChange={(event) => onDialogFillChange({ gradient: event.target.checked })}
            />
          </div>
          {dialogFill.gradient ? (
            <label className="chat-config-dialog__row">
              <span className="chat-config-dialog__label">{t("chat.config.dialogFillGradientMode")}</span>
              <Select
                aria-label={t("chat.config.dialogFillGradientMode")}
                className="chat-config-dialog__select"
                onChange={handleDialogFillGradientModeChange}
                value={dialogFill.gradientMode}
              >
                {dialogFillGradientModeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.labelKey)}
                  </option>
                ))}
              </Select>
            </label>
          ) : null}
          {dialogFill.gradient && dialogFill.gradientMode === "single" ? (
            <label className="chat-config-dialog__row">
              <span className="chat-config-dialog__label">{t("chat.config.dialogFillGradientDirection")}</span>
              <Select
                aria-label={t("chat.config.dialogFillGradientDirection")}
                className="chat-config-dialog__select"
                onChange={handleDialogFillGradientDirectionChange}
                value={dialogFill.gradientDirection}
              >
                {dialogFillGradientDirectionOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.labelKey)}
                  </option>
                ))}
              </Select>
            </label>
          ) : null}
          {dialogFill.gradient && dialogFill.gradientMode === "dual" ? (
            <label className="chat-config-dialog__row">
              <span className="chat-config-dialog__label">{t("chat.config.dialogFillColor2")}</span>
              <input
                aria-label={t("chat.config.dialogFillColor2")}
                className="chat-config-dialog__color-input"
                onChange={(event) => onDialogFillChange({ color2: event.target.value })}
                type="color"
                value={dialogFill.color2}
              />
            </label>
          ) : null}
        </section>

        <section className="chat-config-dialog__section">
          <h3 className="chat-config-dialog__section-title">{t("chat.config.sectionSprites")}</h3>
          {sprites.length ? (
            <div className="chat-config-dialog__sprite-list">
              {sprites.map((sprite, index) => {
                const spriteKey = runtimeSpriteKey(sprite, index);
                const spriteLabel = runtimeSpriteLabel(sprite, index);
                const value = spriteScales[spriteKey] ?? spriteScales[runtimeSpriteDefaultScaleKey] ?? 1;
                return (
                  <label className="chat-config-dialog__row chat-config-dialog__range-row" key={spriteKey}>
                    <span className="chat-config-dialog__label">{spriteLabel}</span>
                    <span className="chat-config-dialog__range-control">
                      <input
                        aria-label={`${t("chat.config.spriteScale")}: ${spriteLabel}`}
                        className="chat-config-dialog__range"
                        max={runtimeSpriteScaleMax}
                        min={runtimeSpriteScaleMin}
                        onChange={(event) =>
                          onSpriteScaleChange(
                            spriteKey,
                            clampRuntimeNumber(event.target.value, value, runtimeSpriteScaleMin, runtimeSpriteScaleMax),
                          )
                        }
                        step={runtimeSpriteScaleStep}
                        type="range"
                        value={value}
                      />
                      <span className="chat-config-dialog__range-value">
                        {t("chat.config.scaleValue", { value: Math.round(value * 100) })}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          ) : (
            <p className="chat-config-dialog__empty">{t("chat.config.spriteEmpty")}</p>
          )}
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.spriteOffsetX")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.spriteOffsetX")}
                className="chat-config-dialog__range"
                max={runtimeSpriteOffsetMax}
                min={runtimeSpriteOffsetMin}
                onChange={handleSpriteOffsetXChange}
                step={runtimeSpriteOffsetStep}
                type="range"
                value={spriteOffsetX}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.spriteOffsetValue", { value: spriteOffsetX })}
              </span>
            </span>
          </label>
          <label className="chat-config-dialog__row chat-config-dialog__range-row">
            <span className="chat-config-dialog__label">{t("chat.config.spriteOffsetY")}</span>
            <span className="chat-config-dialog__range-control">
              <input
                aria-label={t("chat.config.spriteOffsetY")}
                className="chat-config-dialog__range"
                max={runtimeSpriteOffsetMax}
                min={runtimeSpriteOffsetMin}
                onChange={handleSpriteOffsetYChange}
                step={runtimeSpriteOffsetStep}
                type="range"
                value={spriteOffsetY}
              />
              <span className="chat-config-dialog__range-value">
                {t("chat.config.spriteOffsetValue", { value: spriteOffsetY })}
              </span>
            </span>
          </label>
        </section>

        <PluginSlot slot="chat-toolbar" />
      </div>
    </ChatStageModal>
  );
}
