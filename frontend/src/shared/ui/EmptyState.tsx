import type { ReactNode } from "react";

interface EmptyStateProps {
  action?: ReactNode;
  body?: string;
  title: string;
}

export function EmptyState({ action, body, title }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div>
        <p className="empty-state__title">{title}</p>
        {body ? <p className="empty-state__body">{body}</p> : null}
        {action}
      </div>
    </div>
  );
}
