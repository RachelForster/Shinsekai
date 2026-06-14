import type { ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

import "./ExpansionPanelFlow.css";

export interface ExpansionPanelFlowItem {
  accent?: "accent" | "info" | "success" | "warning";
  body: ReactNode;
  description: string;
  done?: boolean;
  icon?: ReactNode;
  id: string;
  title: string;
}

interface ExpansionPanelFlowProps {
  activeId: string;
  items: ExpansionPanelFlowItem[];
  onActiveChange: (id: string) => void;
  title: string;
}

export function ExpansionPanelFlow({ activeId, items, onActiveChange, title }: ExpansionPanelFlowProps) {
  return (
    <section className="expansion-flow" aria-label={title}>
      <header className="expansion-flow__hero">
        <p className="expansion-flow__eyebrow">Setup guide</p>
        <h1>{title}</h1>
      </header>
      <div className="expansion-flow__stack">
        {items.map((item, index) => {
          const open = item.id === activeId;
          return (
            <article
              className="expansion-panel"
              data-accent={item.accent ?? "accent"}
              data-open={open ? "true" : undefined}
              key={item.id}
            >
              <button
                aria-expanded={open}
                className="expansion-panel__summary"
                onClick={() => onActiveChange(item.id)}
                type="button"
              >
                <span className="expansion-panel__index">
                  {item.done ? <Check aria-hidden size={16} /> : String(index + 1).padStart(2, "0")}
                </span>
                <span className="expansion-panel__icon">{item.icon}</span>
                <span className="expansion-panel__copy">
                  <span className="expansion-panel__title">{item.title}</span>
                  <span className="expansion-panel__description">{item.description}</span>
                </span>
                <ChevronDown aria-hidden className="expansion-panel__chevron" size={18} />
              </button>
              <div className="expansion-panel__region" hidden={!open}>
                <div className="expansion-panel__body">{item.body}</div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
