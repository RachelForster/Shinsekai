import type { PageSectionProps } from "../../../shared/ui";
import { VisionSettingsSection } from "../VisionSettingsSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { useApiVisionController } from "../controllers/useApiVisionController";

export function ApiVisionPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const vision = useApiVisionController(ctx);

  return (
    <VisionSettingsSection
      activeApiKey={vision.activeApiKey}
      activeBaseUrl={vision.activeBaseUrl}
      activeModel={vision.activeModel}
      apiKeyRequired={vision.apiKeyRequired}
      availableModelOptions={vision.availableModelOptions}
      disabled={ctx.savePending}
      draft={ctx.draft}
      extraSchema={vision.extraSchema}
      fetchModelsPending={vision.fetchModelsPending}
      id={id}
      onAdapterExtraChange={(key, value) =>
        ctx.updateAdapterExtra("vision_extra_configs", vision.resolvedVisionProvider, key, value)
      }
      onFetchModels={vision.handleFetchModels}
      onProviderChange={vision.updateVisionProvider}
      onProviderMapChange={vision.updateVisionModel}
      onSharedCredentialChange={vision.updateVisionSharedCredential}
      providerOptions={vision.providerOptions}
      sharedLlmProvider={vision.sharedLlmProvider}
    />
  );
}
