import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Search, Star, Trash2, Users } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { getCharacterDisplayName, isSelfPersonaCharacter } from "../../shared/playerCharacterOptions";
import type { Character, CharacterPromptMode } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, TextInput } from "../../shared/ui";
import { CharacterRoleStatus } from "./CharacterRoleStatus";
import { PlayerCharacterFields } from "./PlayerCharacterSettings";
import { getCharacterChipStyle } from "./templateFlow";
import "./CharacterPicker.css";
import "./PrimaryCharacterDialog.css";

function updateDialogCharacterRoles(input: {
  previousSelected: string[];
  nextSelected: string[];
  previousPrimary: string[];
  previousMode?: CharacterPromptMode;
  playerCharacter: string;
}): { primary: string[]; mode: CharacterPromptMode | undefined } {
  const nextPlayer = input.nextSelected.includes(input.playerCharacter) ? input.playerCharacter : "";
  const prevPlayer = input.previousSelected.includes(input.playerCharacter) ? input.playerCharacter : "";
  const prevNpcs = input.previousSelected.filter((name) => name !== prevPlayer);
  const nextNpcs = input.nextSelected.filter((name) => name !== nextPlayer);

  if (nextNpcs.length <= 4) {
    return { primary: [...input.nextSelected], mode: "full" };
  }
  if (input.previousMode === "compact") {
    const remainingPrimaryNpcs = input.previousPrimary.filter((name) => nextNpcs.includes(name));
    if (remainingPrimaryNpcs.length > 0) {
      return { primary: remainingPrimaryNpcs, mode: "compact" };
    }
    return { primary: [], mode: undefined };
  }
  if (input.previousMode === "full" && prevNpcs.length > 4) {
    return { primary: [...input.nextSelected], mode: "full" };
  }
  const remaining = input.previousPrimary.filter((name) => nextNpcs.includes(name));
  return { primary: remaining, mode: undefined };
}

export interface CharacterConfigCommit {
  selectedCharacters: string[];
  characterPromptMode?: CharacterPromptMode;
  primaryCharacters: string[];
  playerCharacter: string;
  readPlayerSpeech: boolean;
  allowPlayerDialogue: boolean;
}

interface CharacterConfigDialogProps {
  open: boolean;
  characters: Character[];
  selectedCharacters: string[];
  characterPromptMode?: CharacterPromptMode;
  primaryCharacters: string[];
  playerCharacter: string;
  readPlayerSpeech: boolean;
  allowPlayerDialogue: boolean;
  pending?: boolean;
  error?: string;
  onClose: () => void;
  onConfirm: (next: CharacterConfigCommit) => Promise<void> | void;
}

export function CharacterConfigDialog({
  open,
  characters,
  selectedCharacters,
  characterPromptMode,
  primaryCharacters,
  playerCharacter,
  readPlayerSpeech,
  allowPlayerDialogue,
  pending = false,
  error,
  onClose,
  onConfirm,
}: CharacterConfigDialogProps) {
  const { t } = useI18n();
  const [searchQuery, setSearchQuery] = useState("");
  const [draftSelected, setDraftSelected] = useState<string[]>([]);
  const [draftPromptMode, setDraftPromptMode] = useState<CharacterPromptMode | undefined>(undefined);
  const [draftPrimary, setDraftPrimary] = useState<string[]>([]);
  const [draftPlayer, setDraftPlayer] = useState("");
  const [draftReadSpeech, setDraftReadSpeech] = useState(false);
  const [draftAllowDialogue, setDraftAllowDialogue] = useState(true);
  const [roleEditorOpen, setRoleEditorOpen] = useState(false);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) {
      return;
    }
    wasOpenRef.current = true;
    setSearchQuery("");
    setDraftSelected([...selectedCharacters]);
    setDraftPromptMode(characterPromptMode);
    setDraftPrimary([...primaryCharacters]);
    setDraftPlayer(playerCharacter);
    setDraftReadSpeech(readPlayerSpeech);
    setDraftAllowDialogue(allowPlayerDialogue);
    setRoleEditorOpen(false);
  }, [
    allowPlayerDialogue,
    characterPromptMode,
    open,
    playerCharacter,
    primaryCharacters,
    readPlayerSpeech,
    selectedCharacters,
  ]);

  const effectiveDraftPlayer = draftSelected.includes(draftPlayer) ? draftPlayer : "";
  const selectedSet = useMemo(() => new Set(draftSelected), [draftSelected]);
  const selectedRecords = useMemo(
    () => characters.filter((character) => selectedSet.has(character.name)),
    [characters, selectedSet],
  );
  const playerCandidates = useMemo(() => {
    const selfPersonas = characters.filter((character) => isSelfPersonaCharacter(character));
    const seen = new Set<string>();
    const result: Character[] = [];
    for (const item of [...selfPersonas, ...selectedRecords]) {
      if (!seen.has(item.name)) {
        seen.add(item.name);
        result.push(item);
      }
    }
    return result;
  }, [characters, selectedRecords]);
  const npcRecords = useMemo(
    () => selectedRecords.filter((character) => character.name !== effectiveDraftPlayer),
    [effectiveDraftPlayer, selectedRecords],
  );
  const npcNames = useMemo(() => npcRecords.map((character) => character.name), [npcRecords]);

  const filteredCharacters = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) {
      return characters;
    }
    return characters.filter((character) => {
      const displayName = getCharacterDisplayName(character).toLowerCase();
      return character.name.toLowerCase().includes(query) || displayName.includes(query);
    });
  }, [characters, searchQuery]);

  const unavailableSelected = useMemo(
    () => draftSelected.filter((name) => !characters.some((character) => character.name === name)),
    [characters, draftSelected],
  );

  const showRolePicker = npcRecords.length > 0 && roleEditorOpen;
  const candidatePrimary = useMemo(() => {
    const valid = draftPrimary.filter((name) => npcNames.includes(name));
    if (valid.length > 0) {
      return valid;
    }
    return npcNames[0] ? [npcNames[0]] : [];
  }, [draftPrimary, npcNames]);
  const primarySet = useMemo(() => new Set(candidatePrimary), [candidatePrimary]);

  const applySelectionChange = (next: string[]) => {
    const roles = updateDialogCharacterRoles({
      previousSelected: draftSelected,
      nextSelected: next,
      previousPrimary: draftPrimary,
      previousMode: draftPromptMode,
      playerCharacter: draftPlayer,
    });
    setDraftSelected(next);
    setDraftPromptMode(roles.mode);
    setDraftPrimary(roles.primary);
    if (!next.includes(draftPlayer)) {
      setDraftPlayer("");
    }
  };

  const toggleCharacter = (name: string) => {
    const next = selectedSet.has(name) ? draftSelected.filter((item) => item !== name) : [...draftSelected, name];
    applySelectionChange(next);
  };

  const handleSelectPlayer = (nextPlayer: string) => {
    if (nextPlayer && !draftSelected.includes(nextPlayer)) {
      setDraftSelected((current) => [...current, nextPlayer]);
    }
    setDraftPlayer(nextPlayer);
  };

  const handleUseAllPrimary = () => {
    setDraftPrimary([...draftSelected]);
    setDraftPromptMode("full");
    setRoleEditorOpen(false);
  };

  const togglePrimaryCandidate = (name: string) => {
    const base = candidatePrimary;
    const exists = base.includes(name);
    if (exists && base.length <= 1) {
      return;
    }
    const nextPrimary = exists ? base.filter((item) => item !== name) : [...base, name];
    setDraftPrimary(nextPrimary);
    setDraftPromptMode("compact");
  };

  const handleApplyRoles = () => {
    setDraftPrimary(candidatePrimary);
    setDraftPromptMode("compact");
    setRoleEditorOpen(false);
  };

  const handleConfirm = async () => {
    const effectiveMode = roleEditorOpen && !draftPromptMode ? "compact" : draftPromptMode;
    const resolvedPrimary =
      effectiveMode === "compact"
        ? candidatePrimary
        : effectiveMode === "full"
          ? [...draftSelected]
          : draftPrimary.filter((name) => draftSelected.includes(name));
    await onConfirm({
      selectedCharacters: draftSelected,
      characterPromptMode: effectiveMode,
      primaryCharacters: resolvedPrimary,
      playerCharacter: effectiveDraftPlayer,
      readPlayerSpeech: Boolean(effectiveDraftPlayer && draftReadSpeech),
      allowPlayerDialogue: draftAllowDialogue,
    });
  };

  return (
    <Dialog
      bodyClassName="template-editor-dialog__body"
      className="template-editor-dialog template-editor-dialog--characters"
      closeLabel={t("common.close")}
      dismissible={!pending}
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <AsyncButton
            icon={<Check aria-hidden className="button__icon" />}
            loading={pending}
            onClick={() => void handleConfirm()}
            variant="primary"
          >
            {t("common.confirm")}
          </AsyncButton>
        </>
      }
      onClose={onClose}
      open={open}
      title={t("template.characterDialog.title")}
    >
      {error ? <p role="alert">{error}</p> : null}

      <div className="template-dialog-toolbar">
        <label className="template-dialog-search">
          <Search aria-hidden className="template-dialog-search__icon" />
          <TextInput
            aria-label={t("template.characterDialog.searchPlaceholder")}
            disabled={pending}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={t("template.characterDialog.searchPlaceholder")}
            value={searchQuery}
          />
        </label>
        <div className="template-dialog-toolbar__actions">
          <Button
            disabled={pending || !characters.length}
            icon={<Users aria-hidden className="button__icon" />}
            onClick={() => applySelectionChange(characters.map((character) => character.name))}
            variant="ghost"
          >
            {t("template.action.selectAllCharacters")}
          </Button>
          <Button
            disabled={pending || !draftSelected.length}
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={() => applySelectionChange([])}
            variant="ghost"
          >
            {t("template.characterDialog.clearSelection")}
          </Button>
        </div>
      </div>

      <div aria-label={t("template.field.characters")} className="template-dialog-chip-grid" role="group">
        {unavailableSelected.map((name) => (
          <button
            aria-pressed="true"
            className="template-character-card"
            disabled={pending}
            key={name}
            onClick={() => applySelectionChange(draftSelected.filter((item) => item !== name))}
            style={getCharacterChipStyle("")}
            type="button"
          >
            {t("template.character.unavailable", { name })}
          </button>
        ))}
        {filteredCharacters.length === 0 ? (
          <p className="template-dialog-empty">{t("template.characterDialog.emptySearch")}</p>
        ) : (
          filteredCharacters.map((character) => {
            const isSelected = selectedSet.has(character.name);
            return (
              <button
                aria-pressed={isSelected}
                className={`template-character-card${isSelected ? " template-character-card--selected" : ""}`}
                disabled={pending}
                key={character.name}
                onClick={() => toggleCharacter(character.name)}
                style={getCharacterChipStyle(character.color ?? "")}
                title={getCharacterDisplayName(character)}
                type="button"
              >
                <span aria-hidden className="template-character-card__dot" />
                <span className="template-character-card__name">{getCharacterDisplayName(character)}</span>
              </button>
            );
          })
        )}
      </div>

      <CharacterRoleStatus
        disabled={pending}
        hasPlayerCharacter={Boolean(effectiveDraftPlayer)}
        mode={draftPromptMode}
        onConfigure={() => setRoleEditorOpen((current) => !current)}
        onUseAll={handleUseAllPrimary}
        primaryCount={
          draftPromptMode === "full"
            ? npcRecords.length
            : candidatePrimary.filter((name) => name !== effectiveDraftPlayer).length
        }
        selectedCount={npcRecords.length}
      />

      {showRolePicker ? (
        <section className="template-dialog-subsection">
          <div className="template-dialog-subsection__header">
            <h3 className="template-dialog-subsection__title">{t("template.primaryCharacters.title")}</h3>
            <div className="template-dialog-toolbar__actions">
              <Button disabled={pending} onClick={handleUseAllPrimary} variant="ghost">
                {t("template.primaryCharacters.useAll")}
              </Button>
              <Button disabled={pending || !candidatePrimary.length} onClick={handleApplyRoles}>
                {t("template.primaryCharacters.confirm")}
              </Button>
            </div>
          </div>
          <p className="template-dialog-subsection__hint">
            {t("template.primaryCharacters.description", { count: npcRecords.length })}
          </p>
          <div className="primary-character-dialog__grid">
            {npcRecords.map((character) => {
              const isPrimary = primarySet.has(character.name);
              const hasBrief = Boolean(character.character_brief?.trim());
              return (
                <button
                  aria-pressed={isPrimary}
                  className={`primary-character-dialog__card${isPrimary ? " primary-character-dialog__card--selected" : ""}`}
                  disabled={pending}
                  key={character.name}
                  onClick={() => togglePrimaryCandidate(character.name)}
                  style={getCharacterChipStyle(character.color || "")}
                  type="button"
                >
                  <span className="primary-character-dialog__name">
                    <Star aria-hidden className="primary-character-dialog__star" />
                    {getCharacterDisplayName(character)}
                  </span>
                  <span className="primary-character-dialog__status">
                    {isPrimary
                      ? t("template.primaryCharacters.primary")
                      : hasBrief
                        ? t("template.primaryCharacters.hasBrief")
                        : t("template.primaryCharacters.needsBrief")}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {playerCandidates.length > 0 ? (
        <section className="template-dialog-subsection">
          <PlayerCharacterFields
            allowDialogue={draftAllowDialogue}
            characters={playerCandidates}
            disabled={pending}
            onAllowDialogue={setDraftAllowDialogue}
            onReadSpeech={setDraftReadSpeech}
            onSelect={handleSelectPlayer}
            readSpeech={draftReadSpeech}
            selected={effectiveDraftPlayer}
          />
        </section>
      ) : null}
    </Dialog>
  );
}
