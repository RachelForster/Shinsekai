import { ExternalLink } from "lucide-react";

import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";
import { resourceLinks } from "./apiSettingsUtils";

export function ResourceLinksSection() {
  const { t } = useI18n();

  return (
    <section className="section resource-links">
      <div className="section__header">
        <h2 className="section__title">{t("api.links.title")}</h2>
      </div>
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
    </section>
  );
}
