import { useI18n } from "../../shared/i18n";
import { Button, Dialog, TextArea } from "../../shared/ui";

interface SpriteTagsDialogProps {
  draft: string;
  onChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
  open: boolean;
}

export function SpriteTagsDialog({ draft, onChange, onClose, onConfirm, open }: SpriteTagsDialogProps) {
  const { t } = useI18n();

  return (
    <Dialog
      bodyClassName="sprite-tags-dialog__body"
      className="sprite-tags-dialog"
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
      title={t("character.sprite.batchTagsTitle")}
    >
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("character.field.emotionTags")}</span>
        <span className="field-row__control">
          <TextArea onChange={(event) => onChange(event.target.value)} rows={12} value={draft} />
        </span>
      </label>
      <p className="sprite-tags-dialog__hint">{t("character.sprite.batchTagsHelp")}</p>
    </Dialog>
  );
}
