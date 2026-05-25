import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useState } from "react";
import { FolderOpen } from "lucide-react";

import type { PathPickerMode } from "../platform/types";
import { IconButton } from "./IconButton";
import { PathPickerDialog } from "./PathPickerDialog";

export function TextInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={["input", className].filter(Boolean).join(" ")} {...props} />;
}

export function TextArea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={["textarea", className].filter(Boolean).join(" ")} {...props} />;
}

export function Select({ className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={["select", className].filter(Boolean).join(" ")} {...props}>
      {children}
    </select>
  );
}

export function NumberInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <TextInput inputMode="decimal" type="number" {...props} />;
}

export function ColorInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <TextInput type="text" {...props} />;
}

interface FilePickerProps extends InputHTMLAttributes<HTMLInputElement> {
  acceptedExtensions?: string[];
  onPick?: () => void;
  onPathChange?: (path: string) => void;
  onPathsChange?: (paths: string[]) => void;
  pickLabel?: string;
  pickerMode?: PathPickerMode;
  pickerTitle?: string;
}

export function FilePicker({
  acceptedExtensions,
  disabled,
  multiple,
  onChange,
  onPathChange,
  onPathsChange,
  onPick,
  pickLabel = "Choose file",
  pickerMode = "file",
  pickerTitle,
  readOnly,
  value,
  ...props
}: FilePickerProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const handlePick = onPick ?? (() => setPickerOpen(true));

  return (
    <>
      <div className="input-group">
        <TextInput disabled={disabled} onChange={onChange} readOnly={readOnly ?? !onChange} value={value} {...props} />
        <IconButton disabled={disabled} label={pickLabel} onClick={handlePick}>
          <FolderOpen aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      <PathPickerDialog
        acceptedExtensions={acceptedExtensions}
        multiple={Boolean(multiple)}
        mode={pickerMode}
        onClose={() => setPickerOpen(false)}
        onSelect={(path) => onPathChange?.(path)}
        onSelectMany={(paths) => {
          if (onPathsChange) {
            onPathsChange(paths);
            return;
          }
          if (paths[0]) {
            onPathChange?.(paths[0]);
          }
        }}
        open={pickerOpen}
        title={pickerTitle || pickLabel}
        value={!multiple && typeof value === "string" ? value : ""}
      />
    </>
  );
}
