import type { SystemConfig } from "../../../entities/config/types";
import type { FormGroupSchema } from "../../../shared/form-schema";
import { SchemaDrivenForm, type PageSectionProps } from "../../../shared/ui";
import type { SystemSettingsPageContext } from "../systemSettingsContext";

export function createSystemGroupComponent(group: FormGroupSchema<SystemConfig>) {
  return function SystemSchemaGroupSection({ ctx }: PageSectionProps<SystemSettingsPageContext>) {
    return (
      <SchemaDrivenForm
        disabled={ctx.savePending}
        errors={ctx.errors}
        groups={[group]}
        onChange={ctx.setDraft}
        sectionIdPrefix="system-"
        value={ctx.draft}
      />
    );
  };
}
