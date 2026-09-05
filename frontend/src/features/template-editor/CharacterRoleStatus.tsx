import type { CharacterPromptMode } from "../../shared/platform/types";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";
import "./CharacterRoleStatus.css";

interface CharacterRoleStatusProps {
  mode?: CharacterPromptMode;
  onConfigure: () => void;
  onUseAll: () => void;
  primaryCount: number;
  selectedCount: number;
}

export function CharacterRoleStatus({
  mode,
  onConfigure,
  onUseAll,
  primaryCount,
  selectedCount,
}: CharacterRoleStatusProps) {
  const { t } = useI18n();

  if (selectedCount <= 4) {
    return null;
  }

  const resolvedPrimaryCount = Math.min(primaryCount, selectedCount);
  const status =
    mode === "full"
      ? t("template.primaryCharacters.statusFull", { count: selectedCount })
      : mode === "compact"
        ? t("template.primaryCharacters.statusCompact", {
            primary: resolvedPrimaryCount,
            secondary: selectedCount - resolvedPrimaryCount,
          })
        : t("template.primaryCharacters.statusPending", { count: selectedCount });

  return (
    <div className="character-role-status">
      <p className="character-role-status__text" role="status">
        {status}
      </p>
      <div className="character-role-status__actions">
        <Button onClick={onConfigure} variant="ghost">
          {t(mode ? "template.primaryCharacters.modify" : "template.primaryCharacters.configure")}
        </Button>
        {mode !== "full" ? <Button onClick={onUseAll}>{t("template.primaryCharacters.useAll")}</Button> : null}
      </div>
    </div>
  );
}
