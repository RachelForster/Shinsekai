import { useRef } from "react";
import "./SegmentedTabs.css";

export interface SegmentedTabItem<T extends string> {
  id: T;
  label: string;
}

interface SegmentedTabsProps<T extends string> {
  ariaLabel?: string;
  className?: string;
  items: ReadonlyArray<SegmentedTabItem<T>>;
  idPrefix?: string;
  value: T;
  onChange: (value: T) => void;
  variant?: "pills" | "underline";
}

export function SegmentedTabs<T extends string>({
  ariaLabel = "Subpages",
  className = "",
  items,
  idPrefix,
  onChange,
  value,
  variant = "underline",
}: SegmentedTabsProps<T>) {
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  if (items.length <= 1) {
    return null;
  }

  return (
    <div
      aria-label={ariaLabel}
      className={["segmented-tabs", `segmented-tabs--${variant}`, className].filter(Boolean).join(" ")}
      role="tablist"
    >
      {items.map((item, index) => (
        <button
          ref={(element) => {
            tabs.current[index] = element;
          }}
          id={idPrefix ? `${idPrefix}-${item.id}` : undefined}
          aria-controls={idPrefix ? `${idPrefix}-panel-${item.id}` : undefined}
          aria-selected={item.id === value}
          tabIndex={item.id === value ? 0 : -1}
          className="segmented-tabs__tab"
          key={item.id}
          onClick={() => onChange(item.id)}
          onKeyDown={(event) => {
            const destinations: Record<string, number> = {
              Home: 0,
              End: items.length - 1,
              ArrowLeft: (index - 1 + items.length) % items.length,
              ArrowRight: (index + 1) % items.length,
            };
            const next = destinations[event.key];
            if (next === undefined) return;
            event.preventDefault();
            onChange(items[next].id);
            tabs.current[next]?.focus();
          }}
          role="tab"
          type="button"
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
