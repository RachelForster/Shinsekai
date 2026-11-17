import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import { autoGroupCharacterSprites, saveCharacterSpriteGroups } from "../../entities/character/repository";
import type { Character, Sprite } from "../../entities/config/types";
import { baseName } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import type { AutoGroupSpritesResult } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, EmptyState, Switch } from "../../shared/ui";

interface SmartOutfitGroupDialogProps {
  characterName: string;
  onApplied: (character: Character, groupCount: number) => void;
  onClose: () => void;
  open: boolean;
  sprites: Sprite[];
}

export function SmartOutfitGroupDialog({
  characterName,
  onApplied,
  onClose,
  open,
  sprites,
}: SmartOutfitGroupDialogProps) {
  const { t } = useI18n();
  const [overwriteExisting, setOverwriteExisting] = useState(false);
  const [preview, setPreview] = useState<AutoGroupSpritesResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!open) {
      setOverwriteExisting(false);
      setPreview(null);
      setErrorMessage("");
      setLoading(false);
      setApplying(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || !characterName) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErrorMessage("");
    void autoGroupCharacterSprites({
      apply: false,
      name: characterName,
      overwriteExisting,
    })
      .then((result) => {
        if (!cancelled) {
          setPreview(result);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setPreview(null);
          setErrorMessage(error instanceof Error ? error.message : t("common.operationFailed"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [characterName, open, overwriteExisting, t]);

  const handleApply = async () => {
    if (!preview || !characterName) {
      return;
    }
    setApplying(true);
    setErrorMessage("");
    try {
      const updated = await saveCharacterSpriteGroups({
        assignments: preview.assignments,
        name: characterName,
        spriteGroups: preview.spriteGroups,
      });
      onApplied(updated, preview.groups.length);
      onClose();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("common.operationFailed"));
    } finally {
      setApplying(false);
    }
  };

  return (
    <Dialog
      className="smart-outfit-dialog"
      closeLabel={t("common.close")}
      dismissible={!applying}
      footer={
        <>
          <Button disabled={applying} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <AsyncButton
            disabled={loading || !preview || preview.groups.length === 0}
            icon={<Sparkles aria-hidden className="button__icon" />}
            loading={applying}
            onClick={() => void handleApply()}
            variant="primary"
          >
            {t("spriteGroup.autoGroupApply")}
          </AsyncButton>
        </>
      }
      onClose={onClose}
      open={open}
      title={t("spriteGroup.autoGroupTitle")}
    >
      <div className="smart-outfit-dialog__body">
        <p className="smart-outfit-dialog__intro">{t("spriteGroup.autoGroupIntro")}</p>
        <Switch
          checked={overwriteExisting}
          disabled={loading || applying}
          id="smart-outfit-overwrite"
          onChange={(event) => setOverwriteExisting(event.currentTarget.checked)}
        >
          {t("spriteGroup.autoGroupOverwrite")}
        </Switch>
        {errorMessage ? (
          <p className="field-error" role="alert">
            {errorMessage}
          </p>
        ) : null}
        {loading ? <EmptyState title={t("spriteGroup.autoGroupPreviewLoading")} /> : null}
        {!loading && preview && preview.groups.length === 0 ? (
          <EmptyState title={t("spriteGroup.autoGroupEmpty")} />
        ) : null}
        {!loading && preview && preview.groups.length > 0 ? (
          <>
            <p className="inline-status" role="status">
              {t("spriteGroup.autoGroupSummary", {
                changed: preview.changedCount,
                groups: preview.groups.length,
              })}
            </p>
            <div className="smart-outfit-dialog__groups">
              {preview.groups.map((group) => (
                <div className="smart-outfit-dialog__group-card" key={group.group}>
                  <div className="smart-outfit-dialog__group-header">
                    <strong>{group.group}</strong>
                    <span className="entity-list__meta">{group.count}</span>
                  </div>
                  <div className="smart-outfit-dialog__chips">
                    {group.spriteIndices.map((spriteIndex) => {
                      const filename = baseName(sprites[spriteIndex]?.path ?? "");
                      return (
                        <span className="smart-outfit-dialog__chip" key={spriteIndex}>
                          #{spriteIndex + 1}
                          {filename ? ` · ${filename}` : ""}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </Dialog>
  );
}
