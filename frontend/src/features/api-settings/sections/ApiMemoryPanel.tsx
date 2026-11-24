import type { PageSectionProps } from "../../../shared/ui";
import { MemorySettingsSection } from "../MemorySettingsSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function ApiMemoryPanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  return (
    <MemorySettingsSection disabled={ctx.savePending} draft={ctx.draft} id={id} onChange={ctx.updateDraftSynced} />
  );
}
