import {
  Children,
  isValidElement,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChevronDown } from "lucide-react";

import "./CustomSelect.css";

interface ParsedSelectOption {
  disabled: boolean;
  label: string;
  value: string;
}

type OptionElement = ReactElement<{
  children?: ReactNode;
  disabled?: boolean;
  label?: string;
  value?: number | string;
}>;

function optionLabel(children: ReactNode): string {
  return Children.toArray(children)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") {
        return String(child);
      }
      return "";
    })
    .join("")
    .trim();
}

function parseSelectOptions(children: ReactNode): ParsedSelectOption[] {
  return Children.toArray(children).flatMap((child) => {
    if (!isValidElement(child)) {
      return [];
    }
    if (child.type === "option") {
      const option = child as OptionElement;
      const label = option.props.label ?? optionLabel(option.props.children);
      return [
        {
          disabled: Boolean(option.props.disabled),
          label,
          value: String(option.props.value ?? label),
        },
      ];
    }
    if (child.type === "optgroup") {
      return parseSelectOptions((child as OptionElement).props.children);
    }
    return [];
  });
}

function createSelectChangeEvent(
  value: string,
  props: Pick<SelectHTMLAttributes<HTMLSelectElement>, "id" | "name">,
): ChangeEvent<HTMLSelectElement> {
  const target = {
    id: props.id,
    name: props.name,
    value,
  };
  return {
    currentTarget: target,
    target,
  } as unknown as ChangeEvent<HTMLSelectElement>;
}

function nextEnabledIndex(options: ParsedSelectOption[], start: number, direction: 1 | -1) {
  if (!options.length) {
    return -1;
  }
  for (let offset = 0; offset < options.length; offset += 1) {
    const index = (start + direction * offset + options.length) % options.length;
    if (!options[index]?.disabled) {
      return index;
    }
  }
  return -1;
}

export function CustomSelect({
  children,
  className = "",
  defaultValue,
  disabled,
  id,
  multiple,
  name,
  onChange,
  value,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  const options = useMemo(() => parseSelectOptions(children), [children]);
  const isControlled = value !== undefined;
  const [internalValue, setInternalValue] = useState(() =>
    String(defaultValue ?? options.find((option) => !option.disabled)?.value ?? ""),
  );
  const selectedValue = String(isControlled ? value : internalValue);
  const selectedIndex = options.findIndex((option) => option.value === selectedValue);
  const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : undefined;
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listboxId = id ? `${id}-listbox` : undefined;

  useEffect(() => {
    if (selectedIndex >= 0) {
      setActiveIndex(selectedIndex);
      return;
    }
    setActiveIndex(nextEnabledIndex(options, 0, 1));
  }, [options, selectedIndex]);

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

  const selectOption = (option: ParsedSelectOption | undefined) => {
    if (!option || option.disabled) {
      return;
    }
    if (!isControlled) {
      setInternalValue(option.value);
    }
    if (option.value !== selectedValue) {
      onChange?.(createSelectChangeEvent(option.value, { id, name }));
    }
    setOpen(false);
  };

  const handleNativeChange = (event: ChangeEvent<HTMLSelectElement>) => {
    if (!isControlled) {
      setInternalValue(event.target.value);
    }
    onChange?.(event);
  };

  const openMenu = () => {
    if (disabled || !options.length) {
      return;
    }
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : nextEnabledIndex(options, 0, 1));
    setOpen(true);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      if (!open) {
        openMenu();
        return;
      }
      setActiveIndex((current) => nextEnabledIndex(options, current + direction, direction));
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const nextIndex = event.key === "Home" ? nextEnabledIndex(options, 0, 1) : nextEnabledIndex(options, -1, -1);
      setActiveIndex(nextIndex);
      setOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) {
        selectOption(options[activeIndex]);
        return;
      }
      openMenu();
      return;
    }
    if (event.key === "Escape") {
      setOpen(false);
    }
  };

  if (multiple) {
    return (
      <select
        className={["select", className].filter(Boolean).join(" ")}
        defaultValue={defaultValue}
        disabled={disabled}
        id={id}
        multiple
        name={name}
        onChange={onChange}
        value={value}
        {...props}
      >
        {children}
      </select>
    );
  }

  const activeOptionId = open && activeIndex >= 0 && listboxId ? `${listboxId}-option-${activeIndex}` : undefined;

  return (
    <div className={["custom-select", className].filter(Boolean).join(" ")} ref={rootRef}>
      <select
        aria-hidden="true"
        className="custom-select__native"
        disabled={disabled}
        name={name}
        onChange={handleNativeChange}
        tabIndex={-1}
        value={selectedValue}
      >
        {children}
      </select>
      <button
        aria-activedescendant={activeOptionId}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        className="custom-select__button"
        disabled={disabled}
        id={id}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={handleKeyDown}
        role="combobox"
        type="button"
      >
        <span className={selectedOption ? "custom-select__value" : "custom-select__placeholder"}>
          {selectedOption?.label || ""}
        </span>
        <ChevronDown aria-hidden className="custom-select__icon" />
      </button>
      {open && options.length ? (
        <div className="custom-select__menu" id={listboxId} role="listbox">
          {options.map((option, index) => (
            <button
              aria-disabled={option.disabled || undefined}
              aria-selected={option.value === selectedValue}
              className="custom-select__option"
              data-active={index === activeIndex || undefined}
              disabled={option.disabled}
              id={listboxId ? `${listboxId}-option-${index}` : undefined}
              key={`${option.value}-${index}`}
              onClick={() => selectOption(option)}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => {
                if (!option.disabled) {
                  setActiveIndex(index);
                }
              }}
              role="option"
              type="button"
            >
              <span className="custom-select__option-label">{option.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
