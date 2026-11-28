import type { CSSProperties } from "react";

import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { Character } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, Select, VisualMedia } from "../../shared/ui";
import type { SpriteCandidate } from "./useSpriteGeneration";

interface SpriteReplaceDialogProps {
  busy: boolean;
  candidate: SpriteCandidate | null;
  error?: string | null;
  onClose: () => void;
  onConfirm: (candidate: SpriteCandidate, targetIndex: number, targetPath: string) => Promise<void>;
  onReplacementIndexChange: (value: string) => void;
  previewProps: {
    "data-sprite-preview-background"?: true;
    "data-sprite-preview-size": string;
    style: CSSProperties;
  };
  replacementIndex: string;
  replacementTags: string[];
  replacing: boolean;
  sprites: Character["sprites"];
}

export function SpriteReplaceDialog({
  busy,
  candidate,
  error,
  onClose,
  onConfirm,
  onReplacementIndexChange,
  previewProps,
  replacementIndex,
  replacementTags,
  replacing,
  sprites,
}: SpriteReplaceDialogProps) {
  const { t } = useI18n();
  const replacementTarget = replacementIndex === "" ? undefined : sprites[Number(replacementIndex)];

  return (
    <Dialog
      open={Boolean(candidate)}
      title={t("spriteGeneration.replace")}
      closeLabel={t("common.close")}
      dismissible={!busy}
      onClose={onClose}
      footer={
        <>
          <Button disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <AsyncButton
            variant="primary"
            disabled={busy || !replacementTarget}
            loading={replacing}
            onClick={async () => {
              if (!candidate || !replacementTarget) return;
              await onConfirm(candidate, Number(replacementIndex), replacementTarget.path);
            }}
          >
            {t("spriteGeneration.confirmReplace")}
          </AsyncButton>
        </>
      }
    >
      <p>{t("spriteGeneration.replaceHint")}</p>
      <label className="field-row field-row--stack">
        <span className="field-row__label">{t("spriteGeneration.replaceTarget")}</span>
        <Select
          aria-label={t("spriteGeneration.replaceTarget")}
          value={replacementIndex}
          disabled={busy}
          onChange={(event) => onReplacementIndexChange(event.target.value)}
        >
          <option value="">{t("spriteGeneration.chooseReplaceTarget")}</option>
          {sprites.map((sprite, index) => (
            <option value={index} key={`${index}:${sprite.path}`}>
              {t("spriteGeneration.sprite", { n: index + 1 })}
              {replacementTags[index] ? ` · ${replacementTags[index]}` : ""}
            </option>
          ))}
        </Select>
      </label>
      <div className="sprite-generation__replace-previews" {...previewProps}>
        <div>
          <p>{t("spriteGeneration.originalSprite")}</p>
          <div className="sprite-generation__preview">
            {replacementTarget ? (
              <VisualMedia alt={t("spriteGeneration.originalSprite")} src={fileUrl(replacementTarget.path)} />
            ) : null}
          </div>
        </div>
        <div>
          <p>{t("spriteGeneration.replacementSprite")}</p>
          <div className="sprite-generation__preview">
            {candidate?.result ? (
              <VisualMedia alt={t("spriteGeneration.replacementSprite")} src={fileUrl(candidate.result.path)} />
            ) : null}
          </div>
        </div>
      </div>
      {error ? (
        <p className="sprite-generation__error" role="alert">
          {error}
        </p>
      ) : null}
    </Dialog>
  );
}
