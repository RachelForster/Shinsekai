import { Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../../shared/i18n";
import type { CharacterRelationGraph } from "../../../shared/platform/types";
import { AsyncButton, Button } from "../../../shared/ui";
import { emptyRelationRow, convertGraphToRows, tableOperations, type RelationRow } from "../model/relationTable";
import type { CharacterRelationController } from "../useCharacterRelationController";

type EditableRelationField = "source" | "target" | "relation" | "temperature";

interface CharacterRelationTableProps {
  actionsContainer: HTMLElement | null;
  graph: CharacterRelationGraph;
  pending: boolean;
  save: CharacterRelationController["save"];
  onDirty: (dirty: boolean) => void;
}

export function CharacterRelationTable({
  graph,
  pending,
  save,
  onDirty,
  actionsContainer,
}: CharacterRelationTableProps) {
  const { t } = useI18n();
  const [rows, setRows] = useState(() => convertGraphToRows(graph));
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const columns = [
    t("relation.tableSource"),
    t("relation.tableTarget"),
    t("relation.tableRelation"),
    t("relation.temperature"),
  ];
  const validationMessages: Record<string, string> = {
    invalidEndpoints: t("relation.invalidEndpoints"),
    invalidTemperature: t("relation.scale"),
    duplicateEdge: t("relation.edgeExists"),
    invalidRelation: t("relation.invalidRelation"),
    tooManyChanges: t("relation.tooManyChanges"),
  };

  const people = graph.nodes;
  const changeRowField = (index: number, field: EditableRelationField, value: string) => {
    setRows((previous) => previous.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
    setDirty(true);
    onDirty(true);
    setError("");
  };
  const deleteRelation = (index: number) => {
    // Retain the original edge to generate delete_edge on save.
    setRows((previous) =>
      previous.map((row, i) =>
        i === index ? { ...emptyRelationRow(), edge: row.edge } : row,
      ),
    );
    setDirty(true);
    onDirty(true);
    setError("");
  };
  const addRelationshipRow = (): void => setRows((previous) => [...previous, emptyRelationRow()]);

  const saveRelationshipChanges = async (): Promise<void> => {
    try {
      const operations = tableOperations(rows, graph.nodes);
      if (!operations.length || (await save(operations))) {
        setDirty(false);
        onDirty(false);
        setError("");
      }
    } catch (validationError: unknown) {
      setError(
        validationMessages[validationError instanceof Error ? validationError.message : ""] ?? String(validationError),
      );
    }
  };

  const cancelRelationshipChanges = (): void => {
    setRows(convertGraphToRows(graph));
    setDirty(false);
    onDirty(false);
    setError("");
  };

  return (
    <div className="relation-sheet">
      <p>{t("relation.tableHint")}</p>
      <div className="page__actions">
        <Button disabled={pending} onClick={addRelationshipRow}>
          {t("relation.addRow")}
        </Button>
        {actionsContainer &&
          createPortal(
            <AsyncButton
              icon={<Save aria-hidden className="button__icon" />}
              variant="primary"
              loading={pending}
              disabled={!dirty}
              onClick={saveRelationshipChanges}
            >
              {t("common.save")}
            </AsyncButton>,
            actionsContainer,
          )}
        <Button disabled={pending || !dirty} onClick={cancelRelationshipChanges}>
          {t("common.cancel")}
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="relation-sheet-scroll">
        <table className="relation-sheet-table" aria-label={t("relation.editTab")}>
          <thead>
            <tr>
              <th scope="col">#</th>
              {columns.map((column) => (
                <th scope="col" key={column}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                <th scope="row">
                  <div className="relation-sheet-row-actions">
                    <span>{index + 1}</span>
                    <button
                      type="button"
                      aria-label={`${t("relation.deleteEdge")} ${index + 1}`}
                      title={t("relation.deleteEdge")}
                      disabled={
                        pending ||
                        (!row.source && !row.target && !row.relation && row.temperature === "0")
                      }
                      onClick={() => deleteRelation(index)}
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  </div>
                </th>
                {(["source", "target"] as const).map((field, column) => (
                  <td key={field}>
                    <select
                      aria-label={`${columns[column]} ${index + 1}`}
                      value={row[field]}
                      disabled={pending}
                      onChange={(e) => changeRowField(index, field, e.target.value)}
                    >
                      <option value="">—</option>
                      {people.map((person, i) => (
                        <option key={`${person.key}-${i}`} value={person.key}>
                          {person.key}
                        </option>
                      ))}
                    </select>
                  </td>
                ))}
                <td>
                  <textarea
                    aria-label={`${columns[2]} ${index + 1}`}
                    placeholder={t("relation.content")}
                    value={row.relation}
                    rows={2}
                    disabled={pending}
                    onChange={(e) =>
                      changeRowField(index, "relation", Array.from(e.target.value).slice(0, 100).join(""))
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`${columns[3]} ${index + 1}`}
                    type="number"
                    min={-10}
                    max={10}
                    step={1}
                    value={row.temperature}
                    disabled={pending}
                    onChange={(e) => changeRowField(index, "temperature", e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
