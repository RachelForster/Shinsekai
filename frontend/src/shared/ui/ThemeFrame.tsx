import type { CSSProperties } from "react";
import "./ThemeFrame.css";

type ThemeFrameStyle = CSSProperties & {
  "--theme-frame-image": string;
  "--theme-frame-outset": string;
  "--theme-frame-slice": string;
  "--theme-frame-width": string;
};

function frameVar(prefix: string, field: string, fallbackPrefix: string | undefined, fallbackValue: string) {
  const fallback = fallbackPrefix ? `var(--${fallbackPrefix}-frame-${field}, ${fallbackValue})` : fallbackValue;
  return `var(--${prefix}-frame-${field}, ${fallback})`;
}

export function ThemeFrame({
  className = "",
  fallbackPrefix,
  prefix,
}: {
  className?: string;
  fallbackPrefix?: string;
  prefix: string;
}) {
  const style: ThemeFrameStyle = {
    "--theme-frame-image": frameVar(prefix, "image", fallbackPrefix, "none"),
    "--theme-frame-outset": frameVar(prefix, "outset", fallbackPrefix, "0px"),
    "--theme-frame-slice": frameVar(prefix, "slice", fallbackPrefix, "32"),
    "--theme-frame-width": frameVar(prefix, "width", fallbackPrefix, "0px"),
  };

  return (
    <span
      aria-hidden="true"
      className={["theme-frame", className].filter(Boolean).join(" ")}
      data-theme-frame={prefix}
      style={style}
    />
  );
}
