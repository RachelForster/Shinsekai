import type { PageSectionProps } from "../../../shared/ui";
import { KnowledgeSettingsSection } from "../KnowledgeSettingsSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function ApiKnowledgePanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  return (
    <KnowledgeSettingsSection disabled={ctx.savePending} draft={ctx.draft} id={id} onChange={ctx.updateDraftSynced} />
  );
}
