import type { PageSectionProps } from "../../../shared/ui";
import { PerceptionSettingsSection } from "../PerceptionSettingsSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function ApiPerceptionPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  return (
    <PerceptionSettingsSection
      disabled={ctx.savePending}
      draft={ctx.draft}
      id={id}
      onChange={ctx.updateDraftSynced}
      savedModel={ctx.data.api_config.perception_model}
      savedUseGguf={ctx.data.api_config.perception_use_gguf}
    />
  );
}
