import type { Dispatch, SetStateAction } from "react";
import { CheckSquare, FolderPlus, Pencil, Sparkles, Star, Trash2 } from "lucide-react";
import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Select, Switch, TextInput } from "../../shared/ui";
import type { CharacterSpritesSectionProps } from "./CharacterSpritesSection";
import { DEFAULT_SPRITE_GROUP } from "./characterEditorUtils";

interface Props {
  activeSpriteGroup: string;
  draft: Character;
  spriteGroups: string[];
  groupCounts: Record<string, number>;
  defaultGroup: string;
  fallbackToDefault: boolean;
  spriteGroupsPending: boolean;
  onApplySpriteGroups: CharacterSpritesSectionProps["onApplySpriteGroups"];
  onOpenSmartGroup: CharacterSpritesSectionProps["onOpenSmartGroup"];
  isSavedCharacter: boolean;
  batchSelectMode: boolean;
  setBatchSelectMode: Dispatch<SetStateAction<boolean>>;
  setCheckedIndices: Dispatch<SetStateAction<Set<number>>>;
  setCreatingGroupOpen: Dispatch<SetStateAction<boolean>>;
  creatingGroupOpen: boolean;
  newGroupInput: string;
  setNewGroupInput: (value: string) => void;
  handleSelectGroupTab: (group: string) => void;
  handleCreateGroup: () => void;
  setPendingDeleteGroup: (group: string) => void;
  renamingGroup: string | null;
  setRenamingGroup: (group: string) => void;
  renameInput: string;
  setRenameInput: (name: string) => void;
  handleConfirmRename: () => void;
  handleSelectVisible: () => void;
  checkedIndices: Set<number>;
  batchTargetGroup: string;
  setBatchTargetGroup: (group: string) => void;
  handleBatchMove: () => void;
}

export function CharacterSpriteGroups({
  activeSpriteGroup,
  draft,
  spriteGroups,
  groupCounts,
  defaultGroup,
  fallbackToDefault,
  spriteGroupsPending,
  onApplySpriteGroups,
  onOpenSmartGroup,
  isSavedCharacter,
  batchSelectMode,
  setBatchSelectMode,
  setCheckedIndices,
  setCreatingGroupOpen,
  creatingGroupOpen,
  newGroupInput,
  setNewGroupInput,
  handleSelectGroupTab,
  handleCreateGroup,
  setPendingDeleteGroup,
  renamingGroup,
  setRenamingGroup,
  renameInput,
  setRenameInput,
  handleConfirmRename,
  handleSelectVisible,
  checkedIndices,
  batchTargetGroup,
  setBatchTargetGroup,
  handleBatchMove,
}: Props) {
  const { t } = useI18n();
  return (
    <div className="sprite-group-panel">
      <div className="sprite-group-bar">
        <div className="sprite-group-tabs" role="tablist">
          <button
            aria-selected={activeSpriteGroup === "__all__"}
            className="sprite-group-tab"
            onClick={() => handleSelectGroupTab("__all__")}
            role="tab"
            type="button"
          >
            {t("spriteGroup.all", { count: draft.sprites.length })}
          </button>
          {spriteGroups.map((group) => (
            <button
              aria-selected={activeSpriteGroup === group}
              className="sprite-group-tab"
              key={group}
              onClick={() => handleSelectGroupTab(group)}
              role="tab"
              type="button"
            >
              <span>{t("spriteGroup.tabCount", { count: groupCounts[group] ?? 0, name: group })}</span>
              {group === defaultGroup ? (
                <span className="sprite-group-tab__badge">{t("spriteGroup.defaultBadge")}</span>
              ) : null}
            </button>
          ))}
        </div>
        <div className="sprite-group-actions">
          <Switch
            checked={fallbackToDefault}
            disabled={spriteGroupsPending}
            id="sprite-group-fallback-default"
            onChange={(event) => onApplySpriteGroups?.({ fallbackToDefaultGroup: event.currentTarget.checked })}
          >
            {t("spriteGroup.fallbackToDefault")}
          </Switch>
          {onOpenSmartGroup ? (
            <Button
              disabled={!isSavedCharacter || !draft.sprites.length}
              icon={<Sparkles aria-hidden className="button__icon" />}
              onClick={onOpenSmartGroup}
              variant="ghost"
            >
              {t("spriteGroup.autoGroup")}
            </Button>
          ) : null}
          <Button
            disabled={!draft.sprites.length}
            icon={<CheckSquare aria-hidden className="button__icon" />}
            onClick={() => {
              setBatchSelectMode((current) => !current);
              setCheckedIndices(new Set());
            }}
            variant={batchSelectMode ? "default" : "ghost"}
          >
            {t(batchSelectMode ? "spriteGroup.batchExitSelectMode" : "spriteGroup.batchSelectMode")}
          </Button>
          <Button
            icon={<FolderPlus aria-hidden className="button__icon" />}
            onClick={() => setCreatingGroupOpen((current) => !current)}
            variant="default"
          >
            {t("spriteGroup.newGroup")}
          </Button>
        </div>
      </div>

      {creatingGroupOpen ? (
        <div className="sprite-group-inline-editor">
          <TextInput
            aria-label={t("spriteGroup.newGroupPlaceholder")}
            onChange={(event) => setNewGroupInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                handleCreateGroup();
              }
            }}
            placeholder={t("spriteGroup.newGroupPlaceholder")}
            value={newGroupInput}
          />
          <AsyncButton
            disabled={!newGroupInput.trim()}
            loading={spriteGroupsPending}
            onClick={handleCreateGroup}
            variant="primary"
          >
            {t("spriteGroup.create")}
          </AsyncButton>
        </div>
      ) : null}

      {activeSpriteGroup !== "__all__" ? (
        <div className="sprite-group-manage-row">
          {activeSpriteGroup !== defaultGroup ? (
            <AsyncButton
              icon={<Star aria-hidden className="button__icon" />}
              loading={spriteGroupsPending}
              onClick={() => onApplySpriteGroups?.({ defaultSpriteGroup: activeSpriteGroup })}
              variant="ghost"
            >
              {t("spriteGroup.setDefault")}
            </AsyncButton>
          ) : null}
          {activeSpriteGroup !== DEFAULT_SPRITE_GROUP ? (
            <>
              <Button
                icon={<Pencil aria-hidden className="button__icon" />}
                onClick={() => {
                  setRenamingGroup(activeSpriteGroup);
                  setRenameInput(activeSpriteGroup);
                }}
                variant="ghost"
              >
                {t("spriteGroup.rename")}
              </Button>
              <Button
                icon={<Trash2 aria-hidden className="button__icon" />}
                onClick={() => setPendingDeleteGroup(activeSpriteGroup)}
                variant="danger"
              >
                {t("spriteGroup.delete")}
              </Button>
            </>
          ) : null}
          {renamingGroup === activeSpriteGroup ? (
            <div className="sprite-group-inline-editor">
              <TextInput
                aria-label={t("spriteGroup.renamePrompt")}
                onChange={(event) => setRenameInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    handleConfirmRename();
                  }
                }}
                placeholder={t("spriteGroup.renamePrompt")}
                value={renameInput}
              />
              <AsyncButton
                disabled={!renameInput.trim() || renameInput.trim() === activeSpriteGroup}
                loading={spriteGroupsPending}
                onClick={handleConfirmRename}
                variant="primary"
              >
                {t("common.save")}
              </AsyncButton>
            </div>
          ) : null}
        </div>
      ) : null}

      {batchSelectMode && draft.sprites.length > 0 ? (
        <div className="sprite-batch-bar">
          <div className="sprite-batch-bar__selection">
            <Button onClick={handleSelectVisible} variant="ghost">
              {t("spriteGroup.batchSelectVisible")}
            </Button>
            <Button disabled={checkedIndices.size === 0} onClick={() => setCheckedIndices(new Set())} variant="ghost">
              {t("spriteGroup.batchClearSelection")}
            </Button>
            <span className="inline-status">{t("spriteGroup.batchSelectedCount", { count: checkedIndices.size })}</span>
          </div>
          <div className="sprite-batch-bar__move">
            <Select
              aria-label={t("spriteGroup.batchMoveChoose")}
              onChange={(event) => setBatchTargetGroup(event.target.value)}
              value={batchTargetGroup}
            >
              <option value="">{t("spriteGroup.batchMoveChoose")}</option>
              {spriteGroups.map((group) => (
                <option key={group} value={group}>
                  {group}
                </option>
              ))}
            </Select>
            <AsyncButton
              disabled={checkedIndices.size === 0 || !batchTargetGroup}
              loading={spriteGroupsPending}
              onClick={handleBatchMove}
              variant="primary"
            >
              {t("spriteGroup.batchMoveTo")}
            </AsyncButton>
          </div>
        </div>
      ) : null}
    </div>
  );
}
