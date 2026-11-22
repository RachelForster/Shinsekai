import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, FileImage, Gamepad2, Plug, Settings } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { useI18n } from "../../shared/i18n";
import { AlertDialog, GuidedFlow } from "../../shared/ui";
import { ApiSetupPanel } from "./steps/ApiSetupPanel";
import { BackgroundSetupPanel } from "./steps/BackgroundSetupPanel";
import { CharacterSetupPanel } from "./steps/CharacterSetupPanel";
import { CompletionSetupPanel } from "./steps/CompletionSetupPanel";
import { PluginSetupPanel } from "./steps/PluginSetupPanel";
import "./OnboardingPage.css";

export type OnboardingStepId = "api" | "plugins" | "characters" | "backgrounds" | "complete";

function isOnboardingStepId(value: unknown): value is OnboardingStepId {
  return (
    value === "api" || value === "plugins" || value === "characters" || value === "backgrounds" || value === "complete"
  );
}

export function OnboardingPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const requestedStep = isOnboardingStepId((location.state as { activeStep?: unknown } | null)?.activeStep)
    ? (location.state as { activeStep: OnboardingStepId }).activeStep
    : undefined;
  const [activeStep, setActiveStep] = useState<OnboardingStepId>(requestedStep ?? "api");
  const [apiSaved, setApiSaved] = useState(false);
  const [pluginsInstalled, setPluginsInstalled] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmBody, setConfirmBody] = useState("");
  const confirmResolver = useRef<((ok: boolean) => void) | null>(null);
  const stepLabel = useCallback((current: number, total: number) => t("onboarding.stepLabel", { current, total }), [t]);

  const showConfirm = useCallback((body: string): Promise<boolean> => {
    return new Promise((resolve) => {
      confirmResolver.current = resolve;
      setConfirmBody(body);
      setConfirmOpen(true);
    });
  }, []);

  const resolveConfirm = useCallback((ok: boolean) => {
    setConfirmOpen(false);
    confirmResolver.current?.(ok);
    confirmResolver.current = null;
  }, []);

  useEffect(() => {
    if (requestedStep) {
      setActiveStep(requestedStep);
    }
  }, [requestedStep]);

  const steps = useMemo(
    () => [
      {
        accent: "accent" as const,
        content: <ApiSetupPanel onSaved={() => setApiSaved(true)} />,
        icon: <Settings aria-hidden size={18} />,
        id: "api",
        title: t("onboarding.api.title"),
      },
      {
        accent: "info" as const,
        content: <PluginSetupPanel onInstalled={() => setPluginsInstalled(true)} />,
        icon: <Plug aria-hidden size={18} />,
        id: "plugins",
        optional: true,
        title: t("onboarding.plugins.title"),
      },
      {
        accent: "success" as const,
        content: <CharacterSetupPanel />,
        icon: <Gamepad2 aria-hidden size={18} />,
        id: "characters",
        title: t("onboarding.characters.title"),
      },
      {
        accent: "warning" as const,
        content: <BackgroundSetupPanel />,
        icon: <FileImage aria-hidden size={18} />,
        id: "backgrounds",
        optional: true,
        title: t("onboarding.backgrounds.title"),
      },
      {
        accent: "accent" as const,
        content: <CompletionSetupPanel />,
        icon: <CheckCircle2 aria-hidden size={18} />,
        id: "complete",
        title: t("onboarding.complete.title"),
      },
    ],
    [t],
  );

  return (
    <>
      <GuidedFlow
        activeId={activeStep}
        backLabel={t("onboarding.actions.previous")}
        beforeNext={(stepId) => {
          if (stepId === "api" && !apiSaved) {
            return showConfirm(t("onboarding.api.unsavedWarning"));
          }
          if (stepId === "plugins" && !pluginsInstalled) {
            return showConfirm(t("onboarding.plugins.uninstalledWarning"));
          }
          return true;
        }}
        finishLabel={t("onboarding.finishLabel")}
        nextLabel={t("onboarding.actions.next")}
        onActiveChange={(id) => {
          if (isOnboardingStepId(id)) {
            setActiveStep(id);
          }
        }}
        onFinish={() => navigate("/settings/templates")}
        optionalLabel={t("onboarding.optionalLabel")}
        requiredLabel={t("onboarding.requiredLabel")}
        stepLabel={stepLabel}
        steps={steps}
        title={t("onboarding.title")}
      />
      <AlertDialog
        body={confirmBody}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.confirm")}
        onCancel={() => resolveConfirm(false)}
        onConfirm={() => resolveConfirm(true)}
        open={confirmOpen}
        title={t("common.confirm")}
      />
    </>
  );
}
