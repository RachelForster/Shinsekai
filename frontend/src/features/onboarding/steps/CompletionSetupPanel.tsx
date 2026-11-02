import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../../shared/ui";
import { OnboardingPanelLayout } from "../OnboardingPanelLayout";
import type { OnboardingCopy } from "../onboardingCopy";

interface CompletionSetupPanelProps {
  copy: OnboardingCopy;
}

export function CompletionSetupPanel({ copy }: CompletionSetupPanelProps) {
  const navigate = useNavigate();

  return (
    <OnboardingPanelLayout
      copy={copy}
      description={copy.complete.description}
      title={copy.complete.title}
      actions={
        <Button
          icon={<ArrowRight aria-hidden size={16} />}
          onClick={() => navigate("/settings/templates")}
          variant="primary"
        >
          {copy.complete.openTemplates}
        </Button>
      }
    >
      <section className="onboarding-complete-banner">
        <div className="onboarding-complete-banner__content">
          <span className="onboarding-complete-banner__eyebrow">{copy.common.done}</span>
          <h2>{copy.complete.bannerTitle}</h2>
          <p>{copy.complete.bannerBody}</p>
        </div>
        <div className="onboarding-complete-banner__mascot" aria-hidden>
          <img alt="" src="/onboarding-catgirl-complete.png" />
        </div>
      </section>
    </OnboardingPanelLayout>
  );
}
