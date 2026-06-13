import { useId, type ChangeEvent, type KeyboardEvent, type MouseEvent } from "react";
import { Languages, X } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import type { ChatCommand } from "../../../shared/platform/types";
import { IconButton, Select } from "../../../shared/ui";
import type { ChatStageSprite } from "../chatState";
import {
  clampRuntimeNumber,
  runtimeDialogOpacityMax,
  runtimeDialogOpacityMin,
  runtimeDialogOpacityStep,
  runtimeDialogScaleMax,
  runtimeDialogScaleMin,
  runtimeDialogScaleStep,
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
} from "../runtimeConfig";

const chatVoiceLanguages = [
  { labelKey: "system.asr.langJa", value: "ja" },
  { labelKey: "system.asr.langEn", value: "en" },
  { labelKey: "system.asr.langZh", value: "zh" },
  { labelKey: "system.asr.langYue", value: "yue" },
] as const;

export function ChatConfigDialog({
  dialogOpacity,
  dialogScale,
  onClose,
  onCommand,
  onDialogOpacityChange,
  onDialogScaleChange,
  onSpriteOffsetXChange,
  onSpriteOffsetYChange,
  onSpriteScaleChange,
  onTextSpeedChange,
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
  dialogOpacity: number;
  dialogScale: number;
  onClose: () => void;
  onCommand: (command: ChatCommand) => void;
  onDialogOpacityChange: (value: number) => void;
  onDialogScaleChange: (value: number) => void;
  onSpriteOffsetXChange: (value: number) => void;
  onSpriteOffsetYChange: (value: number) => void;
  onSpriteScaleChange: (spriteKey: string, value: number) => void;
  onTextSpeedChange: (value: number) => void;
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
  const dialogOpacityPercent = Math.round(dialogOpacity * 100);
  const dialogScalePercent = Math.round(dialogScale * 100);
  const windowScalePercent = Math.round(windowScale * 100);

  if (!open) {
    return null;
  }

  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  };
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

  return (
    <div
      className="chat-config-backdrop"
      data-chat-stage-hitbox="true"
      onMouseDown={handleBackdropMouseDown}
      role="presentation"
    >
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="chat-config-dialog"
        id="chat-stage-dialog-config"
        onKeyDown={handleKeyDown}
        role="dialog"
      >
        <header className="chat-config-dialog__header">
          <div className="chat-config-dialog__heading">
            <h2 className="chat-config-dialog__title" id={titleId}>
              {t("chat.toolbar.config")}
            </h2>
          </div>
          <IconButton className="chat-config-dialog__close" label={t("common.close")} onClick={onClose}>
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </header>
        <div className="chat-config-dialog__body">
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
                              clampRuntimeNumber(
                                event.target.value,
                                value,
                                runtimeSpriteScaleMin,
                                runtimeSpriteScaleMax,
                              ),
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
      </section>
    </div>
  );
}
