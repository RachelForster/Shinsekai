import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { useState } from "react";
import { FolderOpen } from "lucide-react";

import type { PathPickerMode } from "../platform/types";
import { CustomSelect } from "./CustomSelect";
import "./FormControls.css";
import type { FileBrowseHandler } from "./FileManager";
import { IconButton } from "./IconButton";
import { PathDisplay } from "./PathDisplay";
import { PathPickerDialog } from "./PathPickerDialog";

export function TextInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={["input", className].filter(Boolean).join(" ")} {...props} />;
}

export function TextArea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={["textarea", className].filter(Boolean).join(" ")} {...props} />;
}

export function Select({ className = "", children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <CustomSelect className={className} {...props}>
      {children}
    </CustomSelect>
  );
}

export function NumberInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <TextInput inputMode="decimal" type="number" {...props} />;
}

export function ColorInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <TextInput type="color" {...props} />;
}

interface FilePickerProps extends InputHTMLAttributes<HTMLInputElement> {
  acceptedExtensions?: string[];
  onPick?: () => void;
  onPathChange?: (path: string) => void;
  onPathsChange?: (paths: string[]) => void;
  pickLabel?: string;
  pickerBrowse?: FileBrowseHandler;
  pickerInitialPath?: string;
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
  pickerBrowse,
  pickerInitialPath = "",
  pickerMode = "file",
  pickerTitle,
  readOnly,
  value,
  ...props
}: FilePickerProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const handlePick = onPick ?? (() => setPickerOpen(true));
  const showPathDisplay = readOnly ?? !onChange;
  const stringValue = typeof value === "string" ? value : "";

  return (
    <>
      <div className="input-group">
        {showPathDisplay ? (
          <PathDisplay
            className={["path-display--input", disabled ? "path-display--disabled" : ""].filter(Boolean).join(" ")}
            path={stringValue}
          />
        ) : (
          <TextInput disabled={disabled} onChange={onChange} value={value} {...props} />
        )}
        <IconButton disabled={disabled} label={pickLabel} onClick={handlePick}>
          <FolderOpen aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      <PathPickerDialog
        acceptedExtensions={acceptedExtensions}
        multiple={Boolean(multiple)}
        mode={pickerMode}
        onBrowse={pickerBrowse}
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
        value={!multiple && typeof value === "string" ? value || pickerInitialPath : pickerInitialPath}
      />
    </>
  );
}
