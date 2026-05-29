import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import type { LlmModelOption } from "../../shared/platform/types";
import { IconButton, TextInput } from "../../shared/ui";

function capabilityLabel(tag: string) {
  const labels: Record<string, string> = {
    audio: "Audio",
    file: "File",
    image_out: "Image",
    no_access: "No access",
    not_found: "Missing",
    text: "Text",
    unknown: "Unknown",
    video: "Video",
    vision: "Vision",
  };
  return labels[tag] ?? tag;
}

export function ModelCapabilityBadge({ ghost = false, tag }: { ghost?: boolean; tag: string }) {
  return (
    <span className={`llm-model-badge${ghost ? " llm-model-badge--ghost" : ""}`} data-tag={tag}>
      {capabilityLabel(tag)}
    </span>
  );
}

export function EditableModelSelect({
  disabled,
  id,
  onChange,
  options,
  placeholder,
  value,
}: {
  disabled: boolean;
  id: string;
  onChange: (value: string) => void;
  options: LlmModelOption[];
  placeholder: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listboxId = `${id}-listbox`;

  useEffect(() => {
    if (!open) {
      return;
    }

    const closeIfOutside = (target: EventTarget | null) => {
      if (!rootRef.current?.contains(target as Node)) {
        setOpen(false);
      }
    };
    const handlePointerDown = (event: PointerEvent) => closeIfOutside(event.target);
    const handleFocusIn = (event: FocusEvent) => closeIfOutside(event.target);
    const handleWindowBlur = () => setOpen(false);
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("focusin", handleFocusIn, true);
    window.addEventListener("blur", handleWindowBlur);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("focusin", handleFocusIn, true);
      window.removeEventListener("blur", handleWindowBlur);
    };
  }, [open]);

  useEffect(() => {
    if (!options.length) {
      setOpen(false);
    }
  }, [options.length]);

  const selectOption = (modelId: string) => {
    onChange(modelId);
    setOpen(false);
  };

  return (
    <div className="editable-combo" ref={rootRef}>
      <div className="editable-combo__control">
        <TextInput
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={open}
          aria-haspopup="listbox"
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => {
            if (options.length) {
              setOpen(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" && options.length) {
              event.preventDefault();
              setOpen(true);
            }
            if (event.key === "Escape") {
              setOpen(false);
            }
            if (event.key === "Enter" && open) {
              event.preventDefault();
              const exactMatch = options.find((option) => option.id === value);
              if (exactMatch) {
                selectOption(exactMatch.id);
                return;
              }
              setOpen(false);
            }
          }}
          placeholder={placeholder}
          role="combobox"
          value={value}
        />
        <IconButton
          aria-expanded={open}
          className="editable-combo__button"
          disabled={disabled || !options.length}
          label={placeholder}
          onClick={() => setOpen((current) => (options.length ? !current : false))}
        >
          <ChevronDown aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      {open && options.length ? (
        <div className="editable-combo__menu" id={listboxId} role="listbox">
          {options.map((option) => (
            <button
              aria-selected={option.id === value}
              className="editable-combo__option"
              key={option.id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectOption(option.id)}
              role="option"
              type="button"
            >
              <span className="editable-combo__option-main">
                <span className="editable-combo__option-id">{option.id}</span>
                {option.tags.length ? (
                  <span className="editable-combo__option-tags">
                    {option.tags.map((tag) => (
                      <ModelCapabilityBadge ghost key={tag} tag={tag} />
                    ))}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
