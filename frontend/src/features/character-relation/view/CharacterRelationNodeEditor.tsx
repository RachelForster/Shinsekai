import { useQuery } from "@tanstack/react-query";
import { Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { charactersQueryKey, listCharacters } from "../../../entities/character/repository";
import { useI18n } from "../../../shared/i18n";
import type { CharacterRelationGraph, RelationRequest, RelationNode } from "../../../shared/platform/types";
import { AsyncButton, Button, TextInput } from "../../../shared/ui";
import { CharacterPicker } from "../../template-editor/CharacterPicker";
import { getCharacterChipStyle } from "../../template-editor/templateFlow";
import { normalizeRelationName, relationOwnerKey } from "../model/relationSelection";
import type { CharacterRelationController } from "../useCharacterRelationController";

interface CharacterRelationNodeEditorProps {
  actionsContainer: HTMLElement | null;
  graph: CharacterRelationGraph;
  pending: boolean;
  save: CharacterRelationController["save"];
  onDirty: (dirty: boolean) => void;
}

export function CharacterRelationNodeEditor({
  graph,
  pending,
  save,
  onDirty,
  actionsContainer,
}: CharacterRelationNodeEditorProps) {
  const { t } = useI18n();
  const query = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters, retry: false });
  const characters = query.data ?? [];
  const [draft, setDraft] = useState<RelationNode[] | null>(null);
  const [nodeName, setNodeName] = useState("");
  const nodes = draft ?? graph.nodes;
  const ownerKey = relationOwnerKey(graph);
  const newName = nodeName.trim();
  const findLibraryCharacter = (node: RelationNode) =>
    characters.find((character) => normalizeRelationName(character.name) === normalizeRelationName(node.key));
  const selected = nodes.flatMap((node) => {
    const character = findLibraryCharacter(node);
    return character ? [character.name] : [];
  });
  const customNodes = query.isSuccess ? nodes.filter((node) => !findLibraryCharacter(node)) : [];
  const hasNameConflict = nodes.some((node) => normalizeRelationName(node.key) === normalizeRelationName(newName));
  const hasDuplicateNodeKeys = new Set(nodes.map((node) => normalizeRelationName(node.key))).size !== nodes.length;
  const operations: RelationRequest[] = [
    ...graph.nodes
      .filter((node) => node.key !== ownerKey && !nodes.some((next) => next.key === node.key))
      .map((node): RelationRequest => ({ op: "delete_node", key: node.key })),
    ...nodes
      .filter((node) => !graph.nodes.some((previous) => previous.key === node.key))
      .map((node): RelationRequest => ({ op: "add_node", node })),
  ];
  const dirty = Boolean(operations.length || nodeName);
  const disabled = pending || query.isPending || Boolean(query.error);
  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);

  const selectLibraryCharacters = (names: string[]): void => {
    const next = nodes.filter((node) => node.key === ownerKey || !findLibraryCharacter(node));
    for (const name of names) {
      if (next.some((node) => normalizeRelationName(node.key) === normalizeRelationName(name))) continue;
      const existing = graph.nodes.find((node) => normalizeRelationName(node.key) === normalizeRelationName(name));
      next.push(existing ?? { key: name });
    }
    setDraft(next);
  };

  const addCustomNode = (): void => {
    const existing = graph.nodes.find((node) => normalizeRelationName(node.key) === normalizeRelationName(newName));
    setDraft([...nodes, existing ?? { key: newName }]);
    setNodeName("");
  };

  const saveNodeChanges = async (): Promise<void> => {
    const saved = await save(operations);
    if (saved) {
      setDraft(null);
      setNodeName("");
      onDirty(false);
    }
  };

  const cancelNodeChanges = (): void => {
    setDraft(null);
    setNodeName("");
  };

  return (
    <div className="relation-character-picker">
      {query.isPending && <p role="status">{t("common.loading")}</p>}
      {query.error && (
        <div role="alert">
          {String(query.error)} <Button onClick={() => void query.refetch()}>{t("common.retry")}</Button>
        </div>
      )}
      <section className="relation-character-area" aria-label={t("relation.existingCharacters")}>
        <h3 className="template-character-picker__label">{t("relation.existingCharacters")}</h3>
        <CharacterPicker
          characters={characters}
          selected={selected}
          disabled={disabled}
          onChange={selectLibraryCharacters}
        />
      </section>
      <section className="relation-character-area" aria-label={t("relation.customCharacters")}>
        <h3 className="template-character-picker__label">{t("relation.customCharacters")}</h3>
        <div className="relation-custom-header">
          <TextInput
            aria-label={t("relation.nodeName")}
            placeholder={t("relation.nodeName")}
            maxLength={200}
            disabled={disabled}
            value={nodeName}
            onChange={(event) => setNodeName(event.target.value)}
          />
          <Button disabled={disabled || !newName || hasNameConflict} onClick={addCustomNode}>
            {t("common.add")}
          </Button>
        </div>
        <div className="relation-custom-node-list">
          {customNodes.map((node) => (
            <span
              className="template-character-card relation-custom-node"
              style={getCharacterChipStyle("")}
              key={node.key}
            >
              <span className="template-character-card__name" title={node.key}>
                {node.key}
              </span>
              {node.key !== ownerKey && (
                <button
                  type="button"
                  aria-label={`${t("relation.deleteNode")}: ${node.key}`}
                  disabled={disabled}
                  onClick={() => setDraft(nodes.filter((next) => next.key !== node.key))}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              )}
            </span>
          ))}
        </div>
      </section>
      {(hasDuplicateNodeKeys || (newName && hasNameConflict)) && <p role="status">{t("relation.keyConflict")}</p>}
      <div className="page__actions">
        {dirty &&
          actionsContainer &&
          createPortal(
            <AsyncButton
              icon={<Save aria-hidden className="button__icon" />}
              variant="primary"
              loading={pending}
              disabled={disabled || hasDuplicateNodeKeys || !operations.length}
              onClick={saveNodeChanges}
            >
              {t("common.save")}
            </AsyncButton>,
            actionsContainer,
          )}
        {dirty && (
          <Button
            aria-label={`${t("common.cancel")}: ${t("relation.title")}`}
            disabled={pending}
            onClick={cancelNodeChanges}
          >
            {t("common.cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
