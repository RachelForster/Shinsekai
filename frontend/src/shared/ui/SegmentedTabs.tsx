import "./SegmentedTabs.css";

export interface SegmentedTabItem<T extends string> {
  id: T;
  label: string;
}

interface SegmentedTabsProps<T extends string> {
  ariaLabel?: string;
  className?: string;
  items: Array<SegmentedTabItem<T>>;
  value: T;
  onChange: (value: T) => void;
  variant?: "pills" | "underline";
}

export function SegmentedTabs<T extends string>({
  ariaLabel = "Subpages",
  className = "",
  items,
  onChange,
  value,
  variant = "underline",
}: SegmentedTabsProps<T>) {
  if (items.length <= 1) {
    return null;
  }

  return (
    <div
      aria-label={ariaLabel}
      className={["segmented-tabs", `segmented-tabs--${variant}`, className].filter(Boolean).join(" ")}
      role="tablist"
    >
      {items.map((item) => (
        <button
          aria-selected={item.id === value}
          className="segmented-tabs__tab"
          key={item.id}
          onClick={() => onChange(item.id)}
          role="tab"
          type="button"
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
