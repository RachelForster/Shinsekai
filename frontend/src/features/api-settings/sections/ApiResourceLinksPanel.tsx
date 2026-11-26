import type { PageSectionProps } from "../../../shared/ui";
import { ResourceLinksSection } from "../ResourceLinksSection";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function ApiResourceLinksPanel({ id }: PageSectionProps<ApiSettingsPageContext>) {
  return <ResourceLinksSection id={id} />;
}
