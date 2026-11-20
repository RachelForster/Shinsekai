import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { createPortal } from "react-dom";
import { IconButton, TextInput } from "../../../shared/ui";
import "../../../shared/ui/CustomSelect.css";

interface Props {
  label: string;
  value: string;
  options: string[];
  disabled: boolean;
  onChange: (value: string) => void;
}

export function RelationPersonSelect({ label, value, options, disabled, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const root = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 0, width: 0 });
  useEffect(() => {
    if (!open) return;
    const updatePosition = () => {
      const rect = root.current?.getBoundingClientRect();
      if (rect) setPosition({ top: rect.bottom + 3, left: rect.left, width: rect.width });
    };
    updatePosition();
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node))
        setOpen(false);
    };
    document.addEventListener("pointerdown", close, true);
    window.addEventListener("scroll", updatePosition, true);
    window.addEventListener("resize", updatePosition);
    return () => {
      document.removeEventListener("pointerdown", close, true);
      window.removeEventListener("scroll", updatePosition, true);
      window.removeEventListener("resize", updatePosition);
    };
  }, [open]);
  return (
    <div className="editable-combo" ref={root}>
      <div className="editable-combo__control">
        <TextInput
          aria-label={label}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-haspopup="listbox"
          role="combobox"
          maxLength={200}
          disabled={disabled}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
            if (event.key === "ArrowDown") setOpen(true);
          }}
        />
        <IconButton
          className="editable-combo__button"
          label={`${label} ▾`}
          disabled={disabled}
          onClick={() => setOpen(!open)}
        >
          <ChevronDown aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      {open &&
        options.length > 0 &&
        createPortal(
          <div
            className="editable-combo__menu"
            id={listId}
            ref={menu}
            role="listbox"
            style={{ position: "fixed", top: position.top, left: position.left, width: position.width, right: "auto" }}
          >
            {options.map((name) => (
              <button
                key={name}
                type="button"
                role="option"
                aria-selected={value === name}
                className="editable-combo__option"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onChange(name);
                  setOpen(false);
                }}
              >
                {name}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
