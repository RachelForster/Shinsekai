import { AlertDialog } from "../../shared/ui";
import { useI18n } from "../../shared/i18n";
import { type KnowledgeDeleteTarget } from "./useKnowledgeController";

export function KnowledgeDeleteDialogs({
  target,
  pending,
  onCancel,
  onConfirm,
}: {
  target: KnowledgeDeleteTarget | null;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <AlertDialog
      open={Boolean(target)}
      pending={pending}
      title={t(target?.memoryId ? "knowledge.deleteEntry" : "knowledge.deleteKnowledge")}
      body={t(target?.memoryId ? "knowledge.deleteEntryBody" : "knowledge.deleteKnowledgeBody", {
        knowledgeId: target?.knowledgeId ?? "",
        content: target?.content ?? "",
      })}
      cancelLabel={t("common.cancel")}
      closeLabel={t("common.close")}
      confirmLabel={t("common.delete")}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}
