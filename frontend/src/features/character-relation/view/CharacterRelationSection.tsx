import { useState } from "react";

import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { CharacterGraphView } from "./CharacterGraphView";
import { CharacterRelationNodeEditor } from "./CharacterRelationNodeEditor";
import { CharacterRelationTable } from "./CharacterRelationTable";
import { useCharacterRelationController } from "../useCharacterRelationController";

import "./CharacterRelationSection.css";

// Keying the inner editor prevents previous-owner drafts and requests entering another graph.
interface CharacterRelationSectionProps {
  primary: string;
}

export function CharacterRelationSection({ primary }: CharacterRelationSectionProps) {
  return <RelationEditor key={primary} owner={primary} />;
}
interface RelationEditorProps {
  owner: string;
}

function RelationEditor({ owner }: RelationEditorProps) {
  const { t } = useI18n();
  const {
    data: graph,
    isLoading,
    isFetching,
    loadError,
    savePending,
    saveError,
    save,
    reload,
  } = useCharacterRelationController(owner);
  const [tab, setTab] = useState<"edit" | "graph">("edit");
  const [tableDirty, setTableDirty] = useState(false);
  const [nodesDirty, setNodesDirty] = useState(false);
  const [actionsContainer, setActionsContainer] = useState<HTMLDivElement | null>(null);
  return (
    <section className="section page-section-anchor character-relation-section" id="character-relations">
      <div className="section__header">
        <h2 className="section__title">{t("relation.title")}</h2>
        <div className="page__actions" ref={setActionsContainer}>
          <Button
            disabled={!owner || savePending || tableDirty || nodesDirty || isFetching}
            onClick={() => void reload()}
          >
            {t("relation.reload")}
          </Button>
        </div>
      </div>
      <p>{t(owner ? "relation.description" : "relation.saveFirst")}</p>
      {owner && isLoading && <p role="status">{t("relation.loading")}</p>}
      {loadError && <p role="alert">{loadError}</p>}
      {saveError && <p role="alert">{saveError}</p>}
      {graph && (
        <>
          <CharacterRelationNodeEditor
            key={JSON.stringify(graph)}
            graph={graph}
            pending={savePending || tableDirty}
            save={save}
            onDirty={setNodesDirty}
            actionsContainer={actionsContainer}
          />
          <div role="tablist" aria-label={t("relation.title")} className="relation-tabs">
            <Button
              id="relation-edit-tab"
              role="tab"
              aria-selected={tab === "edit"}
              aria-controls="relation-edit-panel"
              onClick={() => setTab("edit")}
            >
              {t("relation.editTab")}
            </Button>
            <Button
              id="relation-graph-tab"
              role="tab"
              aria-selected={tab === "graph"}
              aria-controls="relation-graph-panel"
              onClick={() => setTab("graph")}
            >
              {t("relation.graphTab")}
            </Button>
          </div>
          <div role="tabpanel" id="relation-graph-panel" aria-labelledby="relation-graph-tab" hidden={tab !== "graph"}>
            <CharacterGraphView
              active={tab === "graph"}
              graph={graph}
              disabled={savePending || tableDirty || nodesDirty}
            />
          </div>
          <div role="tabpanel" id="relation-edit-panel" aria-labelledby="relation-edit-tab" hidden={tab !== "edit"}>
            <CharacterRelationTable
              key={JSON.stringify(graph)}
              graph={graph}
              pending={savePending || nodesDirty}
              save={save}
              onDirty={setTableDirty}
              actionsContainer={nodesDirty ? null : actionsContainer}
            />
          </div>
        </>
      )}
    </section>
  );
}
