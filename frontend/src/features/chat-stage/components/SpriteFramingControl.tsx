import {
  defaultVisualFraming,
  normalizeVisualFraming,
  visualFramingMinPosition,
  visualFramingMinRatio,
  type VisualFraming,
} from "../../../modules/character-visual";
import { useI18n } from "../../../shared/i18n";
import { SegmentedRadio } from "../../../shared/ui";

const presets = [
  { id: "full", label: "chat.config.spriteFrameFull", heightRatio: 1 },
  { id: "half", label: "chat.config.spriteFrameHalf", heightRatio: 0.5 },
  { id: "close", label: "chat.config.spriteFrameClose", heightRatio: 0.3 },
] as const;

/** All formats edit the same host-level presentation, never adapter state. */
export function SpriteFramingControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value?: VisualFraming;
  onChange(value: VisualFraming): void;
}) {
  const { t } = useI18n();
  const framing = normalizeVisualFraming(value);
  const positionPercent = Math.round(framing.verticalPosition * 100) || 0;
  const activePreset =
    presets.find((preset) => framing.heightRatio === preset.heightRatio && framing.verticalPosition === 0)?.id ?? null;
  return (
    <div
      className="chat-config-dialog__sprite-framing"
      role="group"
      aria-label={`${t("chat.config.spriteFraming")}: ${label}`}
    >
      <SegmentedRadio
        ariaLabel={`${t("chat.config.spriteFraming")}: ${label}`}
        className="chat-config-dialog__framing-presets"
        onChange={(id) => {
          const preset = presets.find((item) => item.id === id);
          if (preset) {
            onChange({ ...defaultVisualFraming, heightRatio: preset.heightRatio });
          }
        }}
        options={presets.map((preset) => ({ label: t(preset.label), value: preset.id }))}
        size="sm"
        value={activePreset}
      />
      <label className="chat-config-dialog__row chat-config-dialog__range-row">
        <span className="chat-config-dialog__label">{t("chat.config.spriteHeightRatio")}</span>
        <span className="chat-config-dialog__range-control">
          <input
            aria-label={`${t("chat.config.spriteHeightRatio")}: ${label}`}
            className="chat-config-dialog__range"
            type="range"
            min={visualFramingMinRatio * 100}
            max={100}
            step={1}
            value={Math.round(framing.heightRatio * 100)}
            onChange={(event) =>
              onChange(normalizeVisualFraming({ ...framing, heightRatio: Number(event.target.value) / 100 }))
            }
          />
          <span className="chat-config-dialog__range-value">
            {t("chat.config.scaleValue", { value: Math.round(framing.heightRatio * 100) })}
          </span>
        </span>
      </label>
      <label className="chat-config-dialog__row chat-config-dialog__range-row">
        <span className="chat-config-dialog__label">{t("chat.config.spriteFramePosition")}</span>
        <span className="chat-config-dialog__range-control">
          <input
            aria-label={`${t("chat.config.spriteFramePosition")}: ${label}`}
            className="chat-config-dialog__range"
            type="range"
            min={visualFramingMinPosition * 100}
            max={100}
            step={1}
            disabled={framing.heightRatio === 1}
            value={positionPercent}
            onChange={(event) =>
              onChange(normalizeVisualFraming({ ...framing, verticalPosition: Number(event.target.value) / 100 }))
            }
          />
          <span className="chat-config-dialog__range-value">
            {t("chat.config.scaleValue", { value: positionPercent })}
          </span>
        </span>
      </label>
    </div>
  );
}
