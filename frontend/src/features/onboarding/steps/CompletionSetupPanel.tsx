import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { OnboardingPanelLayout } from "../OnboardingPanelLayout";

export function CompletionSetupPanel() {
  const { t } = useI18n();
  const navigate = useNavigate();

  return (
    <OnboardingPanelLayout
      description={t("onboarding.complete.description")}
      title={t("onboarding.complete.title")}
      actions={
        <Button
          icon={<ArrowRight aria-hidden size={16} />}
          onClick={() => navigate("/settings/templates")}
          variant="primary"
        >
          {t("onboarding.complete.openTemplates")}
        </Button>
      }
    >
      <section className="onboarding-complete-banner">
        <div className="onboarding-complete-banner__content">
          <span className="onboarding-complete-banner__eyebrow">{t("onboarding.common.done")}</span>
          <h2>{t("onboarding.complete.bannerTitle")}</h2>
          <p>{t("onboarding.complete.bannerBody")}</p>
        </div>
        <div className="onboarding-complete-banner__mascot" aria-hidden>
          <img alt="" src="/onboarding-catgirl-complete.png" />
        </div>
      </section>
    </OnboardingPanelLayout>
  );
}
