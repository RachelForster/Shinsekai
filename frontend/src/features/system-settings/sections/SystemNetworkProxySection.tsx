import { RefreshCw } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { resolveFormGroupTitle } from "../../../shared/form-schema";
import { AsyncButton, SchemaFieldGrid, type PageSectionProps } from "../../../shared/ui";
import { systemNetworkProxyGroup, type SystemSettingsPageContext } from "../systemSettingsContext";

export function SystemNetworkProxySection({ ctx }: PageSectionProps<SystemSettingsPageContext>) {
  const { t } = useI18n();
  if (!systemNetworkProxyGroup) {
    return null;
  }

  return (
    <section className="section schema-section system-network-proxy page-section-anchor" id="system-network-proxy">
      <div className="section__header">
        <h2 className="section__title">{resolveFormGroupTitle(systemNetworkProxyGroup, t)}</h2>
        <div className="section__actions">
          <AsyncButton
            disabled={ctx.savePending}
            icon={<RefreshCw aria-hidden className="button__icon" />}
            loading={ctx.detectNetworkProxyPending}
            onClick={ctx.runDetectNetworkProxy}
          >
            {t("ops.system.proxy.detectButton")}
          </AsyncButton>
        </div>
      </div>
      <SchemaFieldGrid
        disabled={ctx.savePending}
        errors={ctx.errors}
        group={systemNetworkProxyGroup}
        onChange={ctx.setDraft}
        value={ctx.draft}
      />
    </section>
  );
}
