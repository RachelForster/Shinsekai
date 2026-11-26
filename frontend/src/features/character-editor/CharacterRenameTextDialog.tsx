import { useI18n } from "../../shared/i18n";
import { Button, Dialog } from "../../shared/ui";
import type { CharacterRenameTextPreview } from "./characterRenameText";

interface CharacterRenameTextDialogProps {
  onCancel: () => void;
  onKeepOriginalText: () => void;
  onReplaceText: () => void;
  pending?: boolean;
  preview: CharacterRenameTextPreview | null;
}

export function CharacterRenameTextDialog({
  onCancel,
  onKeepOriginalText,
  onReplaceText,
  pending = false,
  preview,
}: CharacterRenameTextDialogProps) {
  const { t } = useI18n();
  const body = preview
    ? t("character.renameText.body", {
        count: preview.totalMatches,
        newName: preview.newName,
        oldName: preview.oldName,
      })
    : "";

  return (
    <Dialog
      closeLabel={t("common.close")}
      dismissible={!pending}
      footer={
        <>
          <Button disabled={pending} onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button disabled={pending} onClick={onKeepOriginalText}>
            {t("character.renameText.keepOnly")}
          </Button>
          <Button loading={pending} onClick={onReplaceText} variant="primary">
            {t("character.renameText.replaceAndSave")}
          </Button>
        </>
      }
      onClose={onCancel}
      open={Boolean(preview)}
      title={t("character.renameText.title")}
    >
      <p>{body}</p>
    </Dialog>
  );
}
