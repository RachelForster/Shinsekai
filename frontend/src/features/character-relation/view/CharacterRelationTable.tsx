import { ArrowLeftRight, Save, Trash2 } from "lucide-react";
import { Fragment, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { charactersQueryKey, listCharacters } from "../../../entities/character/repository";
import { useI18n } from "../../../shared/i18n";
import type { CharacterRelationGraph } from "../../../shared/platform/types";
import { AsyncButton, Button, Dialog, TextArea, TextInput } from "../../../shared/ui";
import { emptyRelationRow, convertGraphToRows, tableOperations, type RelationRow } from "../model/relationTable";
import type { CharacterRelationController } from "../useCharacterRelationController";
import { RelationPersonSelect } from "./RelationPersonSelect";

type EditableRelationField = "source" | "target" | "relation" | "temperature";

interface CharacterRelationTableProps {
  actionsContainer: HTMLElement | null;
  saveContainer: HTMLElement | null;
  active: boolean;
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
  saveContainer,
  active,
}: CharacterRelationTableProps) {
  const { t } = useI18n();
  const { data: characters = [] } = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters, retry: false });
  const [rows, setRows] = useState(() => convertGraphToRows(graph));
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<{ index: number; text: string } | null>(null);
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

  const people = Array.from(
    new Set([...graph.nodes.map((node) => node.key), ...characters.map((person) => person.name)]),
  );
  const changeRowField = (index: number, field: EditableRelationField, value: string) => {
    setRows((previous) =>
      previous.map((row, i) =>
        i === index ? { ...row, ...(!row.source && !row.target ? { source: graph.owner } : {}), [field]: value } : row,
      ),
    );
    setDirty(true);
    onDirty(true);
    setError("");
  };
  const deleteRelation = (index: number) => {
    // Retain the original edge to generate delete_edge on save.
    setRows((previous) => previous.map((row, i) => (i === index ? { ...emptyRelationRow(), edge: row.edge } : row)));
    setDirty(true);
    onDirty(true);
    setError("");
  };
  const addRelationshipRow = (): void => setRows((previous) => [...previous, emptyRelationRow(graph.owner)]);

  const swapEndpoints = (index: number) => {
    setRows((previous) =>
      previous.map((row, i) => (i === index ? { ...row, source: row.target, target: row.source } : row)),
    );
    setDirty(true);
    onDirty(true);
    setError("");
  };

  const saveRelationshipChanges = async (): Promise<void> => {
    try {
      const operations = tableOperations(rows, graph.nodes, graph.owner);
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
      {active &&
        actionsContainer &&
        createPortal(
          <>
            <Button disabled={pending} onClick={addRelationshipRow}>
              {t("relation.addRow")}
            </Button>
            <Button disabled={pending || !dirty} onClick={cancelRelationshipChanges}>
              {t("relation.cancelChanges")}
            </Button>
          </>,
          actionsContainer,
        )}
      {saveContainer &&
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
          saveContainer,
        )}
      {error && <p role="alert">{error}</p>}
      <div className="relation-rows" aria-label={t("relation.editTab")}>
        <div className="relation-row relation-row--header" aria-hidden="true">
          <span />
          <span className="relation-row__label">{columns[0]}</span>
          <span />
          {columns.slice(1).map((column) => (
            <span className="relation-row__label" key={column}>
              {column}
            </span>
          ))}
        </div>
        {rows.map((row, index) => (
          <div className="relation-row" key={index}>
            <div className="relation-row__number">
              <span>{index + 1}</span>
              <button
                type="button"
                aria-label={`${t("relation.deleteEdge")} ${index + 1}`}
                title={t("relation.deleteEdge")}
                disabled={pending || (!row.source && !row.target && !row.relation && row.temperature === "0")}
                onClick={() => deleteRelation(index)}
              >
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </div>
            {(["source", "target"] as const).map((field, column) => (
              <Fragment key={field}>
                {column === 1 && (
                  <button
                    type="button"
                    className="relation-row__swap"
                    disabled={pending || (!row.source && !row.target)}
                    aria-label={`${t("relation.swapEndpoints")} ${index + 1}`}
                    title={t("relation.swapEndpoints")}
                    onClick={() => swapEndpoints(index)}
                  >
                    <ArrowLeftRight size={16} aria-hidden="true" />
                  </button>
                )}
                <div className="relation-row__field" key={field}>
                  <RelationPersonSelect
                    label={`${columns[column]} ${index + 1}`}
                    value={field === "source" && !row.source && !row.target ? graph.owner : row[field]}
                    disabled={
                      pending || row[field] === graph.owner || (field === "source" && !row.source && !row.target)
                    }
                    options={
                      row.source !== graph.owner && row.target !== graph.owner && (row.source || row.target)
                        ? people
                        : people.filter((person) => person.trim().toLowerCase() !== graph.owner.trim().toLowerCase())
                    }
                    onChange={(value) => changeRowField(index, field, value)}
                  />
                </div>
              </Fragment>
            ))}
            <label className="relation-row__field relation-row__description">
              <TextArea
                aria-label={`${columns[2]} ${index + 1}`}
                placeholder={t("relation.content")}
                value={row.relation}
                rows={1}
                disabled={pending}
                onDoubleClick={() => setDetail({ index, text: row.relation })}
                onChange={(e) => changeRowField(index, "relation", Array.from(e.target.value).slice(0, 100).join(""))}
              />
            </label>
            <label className="relation-row__field">
              <TextInput
                aria-label={`${columns[3]} ${index + 1}`}
                type="number"
                min={-10}
                max={10}
                step={1}
                value={row.temperature}
                disabled={pending}
                onChange={(e) => changeRowField(index, "temperature", e.target.value)}
              />
            </label>
          </div>
        ))}
      </div>
      <Dialog
        open={detail !== null}
        title={t("relation.tableRelation")}
        closeLabel={t("common.cancel")}
        onClose={() => setDetail(null)}
        footer={
          <>
            <Button onClick={() => setDetail(null)}>{t("common.cancel")}</Button>
            <Button
              variant="primary"
              onClick={() => {
                if (detail && detail.text !== rows[detail.index]?.relation)
                  changeRowField(detail.index, "relation", detail.text);
                setDetail(null);
              }}
            >
              {t("relation.addSelected")}
            </Button>
          </>
        }
      >
        <TextArea
          aria-label={t("relation.content")}
          value={detail?.text ?? ""}
          rows={5}
          onChange={(e) =>
            setDetail((current) => current && { ...current, text: Array.from(e.target.value).slice(0, 100).join("") })
          }
        />
      </Dialog>
    </div>
  );
}
