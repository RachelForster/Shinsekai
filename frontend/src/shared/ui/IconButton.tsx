import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import "./IconButton.css";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  label: string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { children, className = "", label, type = "button", ...props },
  ref,
) {
  return (
    <button
      aria-label={label}
      className={["icon-button", className].filter(Boolean).join(" ")}
      ref={ref}
      title={label}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
});
