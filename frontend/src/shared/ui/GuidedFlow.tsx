import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";

import { Button } from "./Button";
import "./GuidedFlow.css";

export interface GuidedFlowStep {
  accent?: "accent" | "info" | "success" | "warning";
  content: ReactNode;
  description: string;
  icon?: ReactNode;
  id: string;
  optional?: boolean;
  title: string;
}

interface GuidedFlowProps {
  activeId?: string;
  backLabel: string;
  finishLabel: string;
  nextLabel: string;
  onActiveChange?: (id: string) => void;
  onFinish?: () => void;
  optionalLabel: string;
  requiredLabel: string;
  steps: GuidedFlowStep[];
  stepLabel: (current: number, total: number) => string;
  title: string;
}

function clampStep(index: number, total: number) {
  return Math.max(0, Math.min(index, Math.max(total - 1, 0)));
}

export function GuidedFlow({
  activeId,
  backLabel,
  finishLabel,
  nextLabel,
  onActiveChange,
  onFinish,
  optionalLabel,
  requiredLabel,
  steps,
  stepLabel,
  title,
}: GuidedFlowProps) {
  const activeIdIndex = activeId ? steps.findIndex((step) => step.id === activeId) : -1;
  const [internalIndex, setInternalIndex] = useState(() =>
    clampStep(activeIdIndex >= 0 ? activeIdIndex : 0, steps.length),
  );
  const activeIndex = clampStep(activeIdIndex >= 0 ? activeIdIndex : internalIndex, steps.length);
  const activeStep = steps[activeIndex];
  const isFirst = activeIndex === 0;
  const isLast = activeIndex === steps.length - 1;

  useEffect(() => {
    setInternalIndex((index) => clampStep(index, steps.length));
  }, [steps.length]);

  const setActiveIndex = (index: number) => {
    const nextIndex = clampStep(index, steps.length);
    setInternalIndex(nextIndex);
    const nextStep = steps[nextIndex];
    if (nextStep) {
      onActiveChange?.(nextStep.id);
    }
  };

  if (!activeStep) {
    return null;
  }

  return (
    <section className="guided-flow" aria-label={title}>
      <header className="guided-flow__header">
        <div className="guided-flow__title-row">
          <div>
            <p className="guided-flow__eyebrow">{stepLabel(activeIndex + 1, steps.length)}</p>
            <h1 className="guided-flow__title">{title}</h1>
          </div>
          <span className="guided-flow__active-requirement" data-optional={activeStep.optional ? "true" : undefined}>
            {activeStep.optional ? optionalLabel : requiredLabel}
          </span>
        </div>
        <nav className="guided-flow__steps" aria-label={title}>
          {steps.map((step, index) => {
            const selected = index === activeIndex;
            const complete = index < activeIndex;
            return (
              <button
                aria-current={selected ? "step" : undefined}
                className="guided-flow__step"
                data-accent={step.accent ?? "accent"}
                data-complete={complete ? "true" : undefined}
                data-selected={selected ? "true" : undefined}
                key={step.id}
                onClick={() => setActiveIndex(index)}
                type="button"
              >
                <span className="guided-flow__step-icon">{complete ? <Check aria-hidden size={15} /> : step.icon}</span>
                <span className="guided-flow__step-copy">
                  <span className="guided-flow__step-title-row">
                    <span className="guided-flow__step-title">{step.title}</span>
                    <span className="guided-flow__step-requirement" data-optional={step.optional ? "true" : undefined}>
                      {step.optional ? optionalLabel : requiredLabel}
                    </span>
                  </span>
                  <span className="guided-flow__step-description">{step.description}</span>
                </span>
              </button>
            );
          })}
        </nav>
      </header>

      <main className="guided-flow__body" data-accent={activeStep.accent ?? "accent"}>
        {activeStep.content}
      </main>

      <footer className="guided-flow__footer">
        <span className="guided-flow__footer-count">{stepLabel(activeIndex + 1, steps.length)}</span>
        <div className="guided-flow__footer-actions">
          <Button
            disabled={isFirst}
            icon={<ArrowLeft aria-hidden size={16} />}
            onClick={() => setActiveIndex(activeIndex - 1)}
          >
            {backLabel}
          </Button>
          <Button
            icon={isLast ? <Check aria-hidden size={16} /> : <ArrowRight aria-hidden size={16} />}
            onClick={() => {
              if (isLast) {
                onFinish?.();
                return;
              }
              setActiveIndex(activeIndex + 1);
            }}
            variant="primary"
          >
            {isLast ? finishLabel : nextLabel}
          </Button>
        </div>
      </footer>
    </section>
  );
}
