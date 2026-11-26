import { useI18n } from "../../../shared/i18n";
import type { PageSectionProps } from "../../../shared/ui";
import { KnowledgeManagerPage } from "../../knowledge-manager/KnowledgeManagerPage";
import type { BackgroundPageContext } from "../backgroundContext";

export function BackgroundKnowledgeSection({ id }: PageSectionProps<BackgroundPageContext>) {
  const { t } = useI18n();

  return (
    <section aria-label={t("knowledge.title")} className="section page-section-anchor" id={id}>
      <KnowledgeManagerPage embedded />
    </section>
  );
}
