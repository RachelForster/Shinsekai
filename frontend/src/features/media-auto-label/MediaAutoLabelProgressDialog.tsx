import { useI18n } from "../../shared/i18n";
import type { ImageAutoLabelResult, TaskSnapshot } from "../../shared/platform/types";
import { Button, Dialog, TaskProgress } from "../../shared/ui";

interface MediaAutoLabelProgressDialogProps {
  onClose: () => void;
  open: boolean;
  pending: boolean;
  result: ImageAutoLabelResult | null;
  task: TaskSnapshot<ImageAutoLabelResult> | null;
}

export function MediaAutoLabelProgressDialog({
  onClose,
  open,
  pending,
  result,
  task,
}: MediaAutoLabelProgressDialogProps) {
  const { t } = useI18n();

  return (
    <Dialog
      closeLabel={t("common.close")}
      dismissible={!pending}
      footer={
        <Button disabled={pending} onClick={onClose}>
          {pending ? t("mediaAutoLabel.running") : t("common.close")}
        </Button>
      }
      onClose={onClose}
      open={open}
      title={t("mediaAutoLabel.progressTitle")}
    >
      {task ? <TaskProgress logLimit={4} task={task} /> : <p>{t("mediaAutoLabel.preparing")}</p>}
      {result && !pending ? (
        <p className="inline-status">
          {t("mediaAutoLabel.complete", {
            annotated: result.annotatedCount,
            failed: result.failedCount,
            skipped: result.skippedCount,
          })}
        </p>
      ) : null}
    </Dialog>
  );
}
