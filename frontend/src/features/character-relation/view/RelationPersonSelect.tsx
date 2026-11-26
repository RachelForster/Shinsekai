import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";
import { TextInput } from "../../../shared/ui";

interface Props {
  label: string;
  value: string;
  options: string[];
  disabled: boolean;
  onChange: (value: string) => void;
}

export function RelationPersonSelect({ label, value, options, disabled, onChange }: Props) {
  const listboxId = useId();
  const root = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>();

  useEffect(() => {
    if (disabled || options.length === 0) setOpen(false);
  }, [disabled, options.length]);

  useEffect(() => {
    if (!open) return;
    const closeIfOutside = (event: Event) => {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !menu.current?.contains(target)) setOpen(false);
    };
    const close = () => setOpen(false);
    document.addEventListener("pointerdown", closeIfOutside, true);
    document.addEventListener("focusin", closeIfOutside, true);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("pointerdown", closeIfOutside, true);
      document.removeEventListener("focusin", closeIfOutside, true);
      window.removeEventListener("blur", close);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const rect = root.current?.getBoundingClientRect();
      if (!rect) return;
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft ?? 0;
      const top = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? window.innerWidth;
      const height = viewport?.height ?? window.innerHeight;
      const padding = 12;
      const gap = 3;
      const below = top + height - padding - rect.bottom - gap;
      const above = rect.top - top - padding - gap;
      const placeAbove = below < 160 && above > below;
      const maxHeight = Math.min(260, Math.max(72, placeAbove ? above : below));
      const menuWidth = Math.min(Math.max(rect.width, 120), Math.max(120, width - padding * 2));
      const menuHeight = Math.min(maxHeight, menu.current?.getBoundingClientRect().height || maxHeight);
      const clamp = (n: number, min: number, max: number) => Math.min(Math.max(n, min), Math.max(min, max));
      setMenuStyle({
        left: clamp(rect.left, left + padding, left + width - padding - menuWidth),
        top: clamp(
          placeAbove ? rect.top - menuHeight - gap : rect.bottom + gap,
          top + padding,
          top + height - padding - menuHeight,
        ),
        width: menuWidth,
        maxHeight,
      });
    };
    position();
    const frame = window.requestAnimationFrame(position);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    window.visualViewport?.addEventListener("resize", position);
    window.visualViewport?.addEventListener("scroll", position);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
      window.visualViewport?.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("scroll", position);
    };
  }, [open, options.length]);

  return (
    <div className="relation-person-select" ref={root}>
      <TextInput
        aria-label={label}
        maxLength={200}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={() => {
          if (!disabled && options.length) setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !disabled && options.length) {
            event.preventDefault();
            setOpen(true);
          } else if (event.key === "Escape" && open) {
            event.preventDefault();
            setOpen(false);
          }
        }}
      />
      <button
        type="button"
        className="custom-select__button relation-person-select__button"
        role="combobox"
        aria-label={`${label} ▾`}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled || options.length === 0}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <ChevronDown aria-hidden size={15} />
      </button>
      {open &&
        options.length > 0 &&
        createPortal(
          <div className="custom-select__menu" id={listboxId} ref={menu} role="listbox" style={menuStyle}>
            {options.map((name) => (
              <button
                type="button"
                role="option"
                aria-selected={name === value}
                className="custom-select__option"
                key={name}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onChange(name);
                  setOpen(false);
                }}
              >
                <span className="custom-select__option-label">{name}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
