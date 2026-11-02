import {
  defaultVisualFraming,
  normalizeVisualFraming,
  visualFramingMinRatio,
  type VisualFraming,
} from "../../../modules/character-visual";
import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";

const presets = [
  { label: "chat.config.spriteFrameFull", heightRatio: 1 },
  { label: "chat.config.spriteFrameHalf", heightRatio: 0.5 },
  { label: "chat.config.spriteFrameClose", heightRatio: 0.3 },
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
  return (
    <div
      className="chat-config-dialog__sprite-framing"
      role="group"
      aria-label={`${t("chat.config.spriteFraming")}: ${label}`}
    >
      <div className="chat-config-dialog__framing-presets">
        {presets.map((preset) => (
          <Button
            key={preset.label}
            variant="ghost"
            aria-pressed={framing.heightRatio === preset.heightRatio && framing.verticalPosition === 0}
            onClick={() => onChange({ ...defaultVisualFraming, heightRatio: preset.heightRatio })}
          >
            {t(preset.label)}
          </Button>
        ))}
      </div>
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
            min={0}
            max={100}
            step={1}
            disabled={framing.heightRatio === 1}
            value={Math.round(framing.verticalPosition * 100)}
            onChange={(event) =>
              onChange(normalizeVisualFraming({ ...framing, verticalPosition: Number(event.target.value) / 100 }))
            }
          />
          <span className="chat-config-dialog__range-value">
            {t("chat.config.scaleValue", { value: Math.round(framing.verticalPosition * 100) })}
          </span>
        </span>
      </label>
    </div>
  );
}
