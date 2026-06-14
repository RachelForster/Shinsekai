import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import type { OnboardingCopy } from "./onboardingCopy";

interface OnboardingPanelLayoutProps {
  actions?: ReactNode;
  children: ReactNode;
  copy: OnboardingCopy;
  description: string;
  done?: boolean;
  title: string;
}

export function OnboardingPanelLayout({
  actions,
  children,
  copy,
  description,
  done,
  title,
}: OnboardingPanelLayoutProps) {
  return (
    <div className="onboarding-panel-layout">
      <div className="onboarding-panel-layout__intro">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        {done ? <span className="onboarding-status-chip">{copy.common.done}</span> : null}
      </div>
      <div className="onboarding-panel-layout__content">{children}</div>
      {actions ? <div className="onboarding-panel-layout__actions">{actions}</div> : null}
    </div>
  );
}

export function FieldBlock({ children, help, label }: { children: ReactNode; help?: string; label: string }) {
  return (
    <label className="onboarding-field">
      <span className="onboarding-field__label">{label}</span>
      {children}
      {help ? <span className="onboarding-field__help">{help}</span> : null}
    </label>
  );
}

export function ExistingList({ emptyLabel, items }: { emptyLabel: string; items: string[] }) {
  if (!items.length) {
    return <p className="onboarding-list-empty">{emptyLabel}</p>;
  }
  return (
    <div className="onboarding-pill-list">
      {items.slice(0, 8).map((item) => (
        <span className="onboarding-pill" key={item}>
          {item}
        </span>
      ))}
    </div>
  );
}

export function OnboardingTaskPanel({
  children,
  defaultOpen = false,
  description,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  description?: string;
  title: string;
}) {
  return (
    <details className="onboarding-task-panel" open={defaultOpen}>
      <summary className="onboarding-task-panel__summary">
        <span>
          <span className="onboarding-task-panel__title">{title}</span>
          {description ? <span className="onboarding-task-panel__description">{description}</span> : null}
        </span>
        <ChevronDown aria-hidden className="onboarding-task-panel__chevron" size={18} />
      </summary>
      <div className="onboarding-task-panel__body">{children}</div>
    </details>
  );
}
