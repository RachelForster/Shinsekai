import { Copy, Eye, Palette, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ComponentType, type SVGProps } from "react";
import { useNavigate } from "react-router-dom";

import { useAppUpdateInfo } from "../../app/shell/useAppUpdateInfo";
import {
  clearPendingFirstInstallBaseline,
  hasPendingFirstInstallBaseline,
  hasSeenOnboarding,
} from "../onboarding/onboardingState";
import { useI18n } from "../../shared/i18n";
import { Button, Dialog } from "../../shared/ui";
import {
  getUnseenReleaseHighlights,
  isReleaseVersion,
  markFeatureVersionSeen,
  readSeenFeatureVersion,
} from "./releaseHighlightsState";
import type { ReleaseHighlightIcon } from "./types";
import "./feature-highlights.css";

const highlightIcons: Record<ReleaseHighlightIcon, ComponentType<SVGProps<SVGSVGElement>>> = {
  copy: Copy,
  palette: Palette,
  preview: Eye,
};

export function FeatureHighlightsPrompt({ enabled }: { enabled: boolean }) {
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const versionQuery = useAppUpdateInfo();
  const [seenVersion, setSeenVersion] = useState(readSeenFeatureVersion);
  const currentVersion = versionQuery.data?.version?.trim() ?? "";
  const needsFirstInstallBaseline = hasPendingFirstInstallBaseline() || !hasSeenOnboarding();
  const unseenReleases = useMemo(
    () => getUnseenReleaseHighlights(currentVersion, seenVersion),
    [currentVersion, seenVersion],
  );

  useEffect(() => {
    if (!needsFirstInstallBaseline || !isReleaseVersion(currentVersion)) {
      return;
    }
    markFeatureVersionSeen(currentVersion);
    clearPendingFirstInstallBaseline();
    setSeenVersion(currentVersion);
  }, [currentVersion, needsFirstInstallBaseline]);

  const open = enabled && !needsFirstInstallBaseline && unseenReleases.length > 0;
  const latestRelease = unseenReleases.at(-1);
  const latestContent = latestRelease?.content[language] ?? latestRelease?.content.zh_CN;

  const dismiss = () => {
    if (!currentVersion) {
      return;
    }
    markFeatureVersionSeen(currentVersion);
    setSeenVersion(currentVersion);
  };

  const explore = () => {
    const destination = latestContent?.actionTo;
    dismiss();
    if (destination) {
      navigate(destination);
    }
  };

  return (
    <Dialog
      bodyClassName="feature-highlights__body"
      className="feature-highlights"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button onClick={dismiss}>{t("releaseHighlights.dismiss")}</Button>
          {latestContent?.actionTo ? (
            <Button onClick={explore} variant="primary">
              {latestContent.actionLabel ?? t("releaseHighlights.explore")}
            </Button>
          ) : null}
        </>
      }
      onClose={dismiss}
      open={open}
      title={t("releaseHighlights.title")}
    >
      <div className="feature-highlights__intro">
        <span className="feature-highlights__mark" aria-hidden>
          <Sparkles />
        </span>
        <div>
          <strong>{latestContent?.title}</strong>
          <p>{latestContent?.summary}</p>
        </div>
      </div>

      <div className="feature-highlights__releases">
        {[...unseenReleases].reverse().map((release) => {
          const content = release.content[language] ?? release.content.zh_CN;
          return (
            <section className="feature-highlights__release" key={release.version}>
              <div className="feature-highlights__version">
                {t("releaseHighlights.version", { version: release.version })}
              </div>
              <div className="feature-highlights__grid">
                {content.features.map((feature) => {
                  const Icon = highlightIcons[feature.icon];
                  return (
                    <article className="feature-highlights__feature" key={feature.title}>
                      {feature.image ? <img alt="" src={feature.image} /> : null}
                      <span className="feature-highlights__icon" aria-hidden>
                        <Icon />
                      </span>
                      <div>
                        <strong>{feature.title}</strong>
                        <p>{feature.description}</p>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </Dialog>
  );
}
