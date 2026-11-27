import { useId, useState } from "react";
import { CircleHelp } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import type { NovelNameMode } from "../../shared/platform/types";
import { SegmentedRadio } from "../../shared/ui";
import type { CastMappingRow } from "./CastMappingTable";
import "./NovelNameModeField.css";

export function hasDuplicateCastTargets(rows: readonly Pick<CastMappingRow, "targetCharacter">[]): boolean {
  const seen = new Set<string>();
  for (const row of rows) {
    const key = row.targetCharacter.trim().toLowerCase();
    if (!key) continue;
    if (seen.has(key)) return true;
    seen.add(key);
  }
  return false;
}

export function NovelNameModeField({
  value,
  onChange,
  disabled = false,
  hasDuplicateTargets = false,
}: {
  value: NovelNameMode;
  onChange: (next: NovelNameMode) => void;
  disabled?: boolean;
  hasDuplicateTargets?: boolean;
}) {
  const { t } = useI18n();
  const labelId = useId();
  const tooltipId = useId();
  const [helpOpen, setHelpOpen] = useState(false);

  return (
    <div className="novel-name-mode">
      <div className="novel-name-mode__bar">
        <div className="novel-name-mode__label-group">
          <span className="field-row__label-text" id={labelId}>
            {t("novel.cast.nameModeLabel")}
          </span>
          <span
            className="field-row__tooltip"
            data-open={helpOpen ? "true" : undefined}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) {
                setHelpOpen(false);
              }
            }}
          >
            <button
              aria-describedby={tooltipId}
              aria-expanded={helpOpen}
              aria-label={t("novel.cast.nameModeHelpLabel")}
              className="field-row__tooltip-trigger novel-name-mode__help-btn"
              onClick={() => setHelpOpen((prev) => !prev)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setHelpOpen(false);
                }
              }}
              type="button"
            >
              <CircleHelp aria-hidden className="field-row__tooltip-icon" />
            </button>
            <span className="field-row__tooltip-bubble novel-name-mode__tooltip" id={tooltipId} role="tooltip">
              {t("novel.cast.nameModeHelp")}
            </span>
          </span>
        </div>
        <SegmentedRadio<NovelNameMode>
          ariaLabelledBy={labelId}
          disabled={disabled}
          onChange={onChange}
          options={[
            { value: "actor", label: t("novel.cast.nameMode.actor") },
            { value: "story", label: t("novel.cast.nameMode.story") },
          ]}
          size="sm"
          value={value}
        />
      </div>
      {value === "actor" && hasDuplicateTargets ? (
        <p className="novel-name-mode__warning" role="note">
          {t("novel.cast.nameModeDuplicateHint")}
        </p>
      ) : null}
    </div>
  );
}
