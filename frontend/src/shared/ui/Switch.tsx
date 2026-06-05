import type { InputHTMLAttributes, ReactNode } from "react";
import "./Switch.css";

interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  children?: ReactNode;
}

export function Switch({ children, className = "", disabled, id, ...props }: SwitchProps) {
  const classes = ["switch", disabled ? "switch--disabled" : "", className].filter(Boolean).join(" ");

  return (
    <label className={classes} htmlFor={id}>
      <input className="switch__input" disabled={disabled} id={id} type="checkbox" {...props} />
      <span className="switch__track">
        <span className="switch__thumb" />
      </span>
      {children ? <span className="switch__label">{children}</span> : null}
    </label>
  );
}
