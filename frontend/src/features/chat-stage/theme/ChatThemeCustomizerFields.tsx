import type { ReactNode } from "react";

import { Select, TextInput } from "../../../shared/ui";

export function ColorField({
  fallback = "#ffffff",
  label,
  onChange,
  value = "",
}: {
  fallback?: string;
  label: string;
  onChange: (value: string) => void;
  value?: string;
}) {
  const pickerValue = /^#[0-9a-f]{6}$/i.test(value.trim()) ? value.trim() : fallback;
  return (
    <div className="chat-theme-customizer__field">
      <span>{label}</span>
      <span className="chat-theme-customizer__color-control">
        <input
          aria-label={`${label} color`}
          onChange={(event) => onChange(event.target.value)}
          type="color"
          value={pickerValue}
        />
        <TextInput aria-label={label} onChange={(event) => onChange(event.target.value)} value={value} />
      </span>
    </div>
  );
}

export function RangeField({
  label,
  max,
  min,
  onChange,
  step = 1,
  suffix = "",
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  step?: number;
  suffix?: string;
  value: number;
}) {
  return (
    <label className="chat-theme-customizer__field chat-theme-customizer__field--range">
      <span>{label}</span>
      <span className="chat-theme-customizer__range-control">
        <input
          aria-label={label}
          max={max}
          min={min}
          onChange={(event) => onChange(Number(event.target.value))}
          step={step}
          type="range"
          value={value}
        />
        <output>
          {value}
          {suffix}
        </output>
      </span>
    </label>
  );
}

export function SelectField({
  children,
  label,
  onChange,
  value,
}: {
  children: ReactNode;
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <label className="chat-theme-customizer__field">
      <span>{label}</span>
      <Select aria-label={label} onChange={(event) => onChange(event.target.value)} value={value}>
        {children}
      </Select>
    </label>
  );
}
