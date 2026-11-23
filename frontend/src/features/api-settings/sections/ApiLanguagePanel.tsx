import type { PageSectionProps } from "../../../shared/ui";
import { ApiLanguageSection } from "../ApiLanguageSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { useApiLanguageController } from "../controllers/useApiLanguageController";

export function ApiLanguagePanel({ ctx, id }: PageSectionProps<ApiSettingsPageContext>) {
  const language = useApiLanguageController(ctx);

  return (
    <ApiLanguageSection
      disabled={language.disabled}
      id={id}
      onChange={language.handleLanguageChange}
      systemDraft={ctx.systemDraft}
    />
  );
}
