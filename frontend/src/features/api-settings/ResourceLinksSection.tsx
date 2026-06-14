import { ExternalLink } from "lucide-react";

import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";
import { resourceLinks } from "./apiSettingsUtils";

interface ResourceLinksSectionProps {
  id?: string;
}

export function ResourceLinksSection({ id }: ResourceLinksSectionProps) {
  const { t } = useI18n();

  return (
    <details className="section schema-section resource-links page-section-anchor" id={id}>
      <summary className="schema-section__summary">{t("api.links.title")}</summary>
      <div className="resource-links__grid">
        {resourceLinks.map(([labelKey, url]) => (
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            key={url}
            onClick={() => openExternal(url)}
            variant="ghost"
          >
            {t(labelKey)}
          </Button>
        ))}
      </div>
      <p className="section__description resource-links__help">{t("api.links.help")}</p>
    </details>
  );
}
