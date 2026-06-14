import { useMemo } from "react";
import { FileImage, Gamepad2, MessageCircle, Plug, Settings } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useI18n } from "../../shared/i18n";
import { GuidedFlow } from "../../shared/ui";
import { onboardingCopy } from "./onboardingCopy";
import { ApiSetupPanel } from "./steps/ApiSetupPanel";
import { BackgroundSetupPanel } from "./steps/BackgroundSetupPanel";
import { CharacterSetupPanel } from "./steps/CharacterSetupPanel";
import { ChatSetupPanel } from "./steps/ChatSetupPanel";
import { PluginSetupPanel } from "./steps/PluginSetupPanel";
import "./OnboardingPage.css";

function format(template: string, values: Record<string, number | string>) {
  return template.replace(/\{(\w+)\}/g, (match, key) => String(values[key] ?? match));
}

export function OnboardingPage() {
  const navigate = useNavigate();
  const { language } = useI18n();
  const copy = onboardingCopy[language] ?? onboardingCopy.zh_CN;
  const stepLabel = (current: number, total: number) => format(copy.stepLabel, { current, total });

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
        content: <ChatSetupPanel copy={copy} />,
        description: copy.chat.description,
        icon: <MessageCircle aria-hidden size={18} />,
        id: "chat",
        title: copy.chat.title,
      },
    ],
    [copy],
  );

  return (
    <GuidedFlow
      backLabel={copy.actions.previous}
      finishLabel={copy.finishLabel}
      nextLabel={copy.actions.next}
      onFinish={() => navigate("/settings/launch")}
      optionalLabel={copy.optionalLabel}
      requiredLabel={copy.requiredLabel}
      stepLabel={stepLabel}
      steps={steps}
      title={copy.title}
    />
  );
}
