import type { ButtonHTMLAttributes, ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

type ButtonVariant = "default" | "primary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: ReactNode;
  loading?: boolean;
  tooltip?: string;
  variant?: ButtonVariant;
}

export function Button({
  children,
  className = "",
  disabled,
  icon,
  loading = false,
  tooltip,
  type = "button",
  variant = "default",
  ...props
}: ButtonProps) {
  const classes = ["button", variant !== "default" ? `button--${variant}` : "", className].filter(Boolean).join(" ");
  return (
    <button className={classes} disabled={disabled || loading} title={tooltip} type={type} {...props}>
      {loading ? <LoaderCircle aria-hidden className="button__spinner" /> : icon}
      {children}
    </button>
  );
}

export function AsyncButton(props: ButtonProps) {
  return <Button {...props} />;
}

export function DangerButton(props: ButtonProps) {
  return <Button {...props} variant="danger" />;
}

export function ToolbarButton(props: ButtonProps) {
  return <Button {...props} variant={props.variant ?? "ghost"} />;
}
