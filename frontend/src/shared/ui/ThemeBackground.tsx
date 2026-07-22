import "./ThemeBackground.css";

export function ThemeBackground({ className = "", prefix }: { className?: string; prefix: string }) {
  return (
    <span
      aria-hidden="true"
      className={["theme-background", className].filter(Boolean).join(" ")}
      data-theme-background={prefix}
    />
  );
}
