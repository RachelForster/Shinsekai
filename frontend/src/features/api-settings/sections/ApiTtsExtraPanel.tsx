import { useI18n } from "../../../shared/i18n";
import type { PageSectionProps } from "../../../shared/ui";
import { AdapterExtraSection } from "../AdapterExtraSection";
import { adapterSchema } from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function ApiTtsExtraPanel({ ctx }: PageSectionProps<ApiSettingsPageContext>) {
  const { t } = useI18n();
  const ttsExtraSchema = adapterSchema(ctx.adapterCatalog?.tts, ctx.draft.tts_provider);

  return (
    <AdapterExtraSection
      disabled={ctx.savePending}
      onChange={(key, value) => ctx.updateAdapterExtra("tts_extra_configs", ctx.draft.tts_provider, key, value)}
      schema={ttsExtraSchema}
      title={t("ops.api.extra.providerTitle", { provider: ctx.draft.tts_provider })}
      values={ctx.draft.tts_extra_configs?.[ctx.draft.tts_provider] ?? {}}
    />
  );
}
