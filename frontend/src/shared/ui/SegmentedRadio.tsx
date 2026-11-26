import { useId, type ReactNode } from "react";
import "./SegmentedRadio.css";

export interface SegmentedRadioOption<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  title?: string;
}

export interface SegmentedRadioProps<T extends string> {
  ariaLabel?: string;
  ariaLabelledBy?: string;
  className?: string;
  disabled?: boolean;
  name?: string;
  onChange: (value: T) => void;
  options: ReadonlyArray<SegmentedRadioOption<T>>;
  size?: "sm" | "md";
  value: T | null | undefined;
}

export function SegmentedRadio<T extends string>({
  ariaLabel,
  ariaLabelledBy,
  className = "",
  disabled = false,
  name,
  onChange,
  options,
  size = "md",
  value,
}: SegmentedRadioProps<T>) {
  const generatedName = useId();
  const groupName = name || generatedName;
  const classes = [
    "segmented-radio",
    `segmented-radio--${size}`,
    disabled ? "segmented-radio--disabled" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div aria-label={ariaLabel} aria-labelledby={ariaLabelledBy} className={classes} role="radiogroup">
      {options.map((option) => {
        const selected = value === option.value;
        const optionDisabled = Boolean(disabled || option.disabled);
        const optionClasses = [
          "segmented-radio__option",
          selected ? "segmented-radio__option--selected" : "",
          optionDisabled ? "segmented-radio__option--disabled" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <label className={optionClasses} key={option.value}>
            <input
              checked={selected}
              className="segmented-radio__input"
              disabled={optionDisabled}
              name={groupName}
              onChange={() => onChange(option.value)}
              type="radio"
              value={option.value}
            />
            <span className="segmented-radio__surface" title={option.title ?? option.label}>
              {option.icon}
              <span className="segmented-radio__label">{option.label}</span>
            </span>
          </label>
        );
      })}
    </div>
  );
}
