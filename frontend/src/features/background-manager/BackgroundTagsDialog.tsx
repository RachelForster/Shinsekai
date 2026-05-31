import { useI18n } from "../../shared/i18n";
import { Button, Dialog, TextArea } from "../../shared/ui";

interface BackgroundTagsDialogProps {
  draft: string;
  fieldLabel: string;
  help: string;
  onChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
  open: boolean;
  title: string;
}

export function BackgroundTagsDialog({
  draft,
  fieldLabel,
  help,
  onChange,
  onClose,
  onConfirm,
  open,
  title,
}: BackgroundTagsDialogProps) {
  const { t } = useI18n();

  return (
    <Dialog
      bodyClassName="background-tags-dialog__body"
      className="background-tags-dialog"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button onClick={onConfirm} variant="primary">
            {t("common.confirm")}
          </Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={title}
    >
      <label className="field-row field-row--stack">
        <span className="field-row__label">{fieldLabel}</span>
        <span className="field-row__control">
          <TextArea onChange={(event) => onChange(event.target.value)} rows={12} value={draft} />
        </span>
      </label>
      <p className="background-tags-dialog__hint">{help}</p>
    </Dialog>
  );
}
