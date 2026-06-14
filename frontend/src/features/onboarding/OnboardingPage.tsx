import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FileImage, Gamepad2, Plug, Settings } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { useI18n } from "../../shared/i18n";
import { GuidedFlow } from "../../shared/ui";
import { onboardingCopy, type OnboardingStepId } from "./onboardingCopy";
import { ApiSetupPanel } from "./steps/ApiSetupPanel";
import { BackgroundSetupPanel } from "./steps/BackgroundSetupPanel";
import { CharacterSetupPanel } from "./steps/CharacterSetupPanel";
import { CompletionSetupPanel } from "./steps/CompletionSetupPanel";
import { PluginSetupPanel } from "./steps/PluginSetupPanel";
import "./OnboardingPage.css";

function format(template: string, values: Record<string, number | string>) {
  return template.replace(/\{(\w+)\}/g, (match, key) => String(values[key] ?? match));
}

function isOnboardingStepId(value: unknown): value is OnboardingStepId {
  return (
    value === "api" || value === "plugins" || value === "characters" || value === "backgrounds" || value === "complete"
  );
}

export function OnboardingPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { language } = useI18n();
  const copy = onboardingCopy[language] ?? onboardingCopy.zh_CN;
  const requestedStep = isOnboardingStepId((location.state as { activeStep?: unknown } | null)?.activeStep)
    ? (location.state as { activeStep: OnboardingStepId }).activeStep
    : undefined;
  const [activeStep, setActiveStep] = useState<OnboardingStepId>(requestedStep ?? "api");
  const stepLabel = (current: number, total: number) => format(copy.stepLabel, { current, total });

  useEffect(() => {
    if (requestedStep) {
      setActiveStep(requestedStep);
    }
  }, [requestedStep]);

  const steps = useMemo(
    () => [
      {
        accent: "accent" as const,
        content: <ApiSetupPanel copy={copy} />,
        description: copy.api.description,
        icon: <Settings aria-hidden size={18} />,
        id: "api",
        title: copy.api.title,
      },
      {
        accent: "info" as const,
        content: <PluginSetupPanel copy={copy} />,
        description: copy.plugins.description,
        icon: <Plug aria-hidden size={18} />,
        id: "plugins",
        optional: true,
        title: copy.plugins.title,
      },
      {
        accent: "success" as const,
        content: <CharacterSetupPanel copy={copy} />,
        description: copy.characters.description,
        icon: <Gamepad2 aria-hidden size={18} />,
        id: "characters",
        title: copy.characters.title,
      },
      {
        accent: "warning" as const,
        content: <BackgroundSetupPanel copy={copy} />,
        description: copy.backgrounds.description,
        icon: <FileImage aria-hidden size={18} />,
        id: "backgrounds",
        optional: true,
        title: copy.backgrounds.title,
      },
      {
        accent: "accent" as const,
        content: <CompletionSetupPanel copy={copy} />,
        description: copy.complete.description,
        icon: <CheckCircle2 aria-hidden size={18} />,
        id: "complete",
        title: copy.complete.title,
      },
    ],
    [copy],
  );

  return (
    <GuidedFlow
      activeId={activeStep}
      backLabel={copy.actions.previous}
      finishLabel={copy.finishLabel}
      nextLabel={copy.actions.next}
      onActiveChange={(id) => {
        if (isOnboardingStepId(id)) {
          setActiveStep(id);
        }
      }}
      onFinish={() => navigate("/settings/templates")}
      optionalLabel={copy.optionalLabel}
      requiredLabel={copy.requiredLabel}
      stepLabel={stepLabel}
      steps={steps}
      title={copy.title}
    />
  );
}
