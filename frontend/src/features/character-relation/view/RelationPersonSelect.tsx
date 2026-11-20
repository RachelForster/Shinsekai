import { useId } from "react";
import { CustomSelect, TextInput } from "../../../shared/ui";

interface Props {
  label: string;
  value: string;
  options: string[];
  disabled: boolean;
  onChange: (value: string) => void;
}

export function RelationPersonSelect({ label, value, options, disabled, onChange }: Props) {
  const selectId = useId();
  return (
    <div className="relation-person-select">
      <TextInput
        aria-label={label}
        maxLength={200}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={() => {
          const picker = document.getElementById(selectId);
          if (picker && !disabled && options.length && picker.getAttribute("aria-expanded") === "false") picker.click();
        }}
        onKeyDown={(event) => {
          const picker = document.getElementById(selectId);
          const expanded = picker?.getAttribute("aria-expanded") === "true";
          if ((event.key === "ArrowDown" && !expanded) || (event.key === "Escape" && expanded)) {
            event.preventDefault();
            picker?.click();
          }
        }}
      />
      <CustomSelect
        id={selectId}
        className="relation-person-select__picker"
        aria-label={`${label} ▾`}
        disabled={disabled || options.length === 0}
        value={options.includes(value) ? value : ""}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </CustomSelect>
    </div>
  );
}
