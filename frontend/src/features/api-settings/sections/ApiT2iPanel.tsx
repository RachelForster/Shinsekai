import type { PageSectionProps } from "../../../shared/ui";
import { T2iSetupSection } from "../T2iSetupSection";
import { adapterSchema, t2iProviderSelectOptions } from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function ApiT2iPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const t2iProviderOptions = t2iProviderSelectOptions(ctx.adapterCatalog, ctx.draft.t2i_provider);
  const t2iExtraSchema = adapterSchema(ctx.adapterCatalog?.t2i, ctx.draft.t2i_provider);

  return (
    <T2iSetupSection
      disabled={ctx.savePending}
      draft={ctx.draft}
      errors={ctx.errors}
      extraSchema={t2iExtraSchema}
      extraValues={ctx.draft.t2i_extra_configs?.[ctx.draft.t2i_provider] ?? {}}
      id={id}
      onAdapterExtraChange={(key, value) =>
        ctx.updateAdapterExtra("t2i_extra_configs", ctx.draft.t2i_provider, key, value)
      }
      onChange={ctx.updateDraftSynced}
      providerOptions={t2iProviderOptions}
    />
  );
}
