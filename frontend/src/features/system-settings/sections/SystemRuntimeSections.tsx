import { useI18n } from "../../../shared/i18n";
import { getRuntimeTarget, isRemotePcActive } from "../../../shared/platform/runtimeTarget";
import { Button, type PageSectionProps } from "../../../shared/ui";
import { DesktopBackgroundSection } from "../DesktopBackgroundSection";
import { DesktopRuntimeSection } from "../DesktopRuntimeSection";
import type { SystemSettingsPageContext } from "../systemSettingsContext";

export function SystemDesktopRuntimeSection() {
  return <DesktopRuntimeSection />;
}

export function SystemDesktopBackgroundSection() {
  return <DesktopBackgroundSection />;
}

export function SystemCrossPlatformSection({ ctx }: PageSectionProps<SystemSettingsPageContext>) {
  const { t } = useI18n();
  return (
    <section className="section page-section-anchor" id="system-cross-platform">
      <div className="section__header">
        <h2 className="section__title">{t("ops.system.crossPlatformTitle")}</h2>
        <div className="section__actions">
          <Button onClick={ctx.openRuntimeModeDialog} variant="primary">
            {t("ops.system.crossPlatformButton")}
          </Button>
        </div>
      </div>
      <p className="page__subtitle">
        {isRemotePcActive()
          ? t("ops.system.crossPlatformRemote")
          : getRuntimeTarget() === "toy"
            ? t("ops.system.crossPlatformToy")
            : getRuntimeTarget() === "mobile"
              ? t("ops.system.crossPlatformMobile")
              : t("ops.system.crossPlatformStandalone")}
      </p>
    </section>
  );
}
