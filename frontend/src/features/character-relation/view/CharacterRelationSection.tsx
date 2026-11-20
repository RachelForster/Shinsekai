import { useState } from "react";

import { useI18n } from "../../../shared/i18n";
import { Button, Dialog } from "../../../shared/ui";
import { CharacterGraphView } from "./CharacterGraphView";
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
    clean,
  } = useCharacterRelationController(owner);
  const [tab, setTab] = useState<"edit" | "graph">("edit");
  const [tableDirty, setTableDirty] = useState(false);
  const [cleanDialogOpen, setCleanDialogOpen] = useState(false);
  const [actionsContainer, setActionsContainer] = useState<HTMLDivElement | null>(null);
  const [saveContainer, setSaveContainer] = useState<HTMLDivElement | null>(null);
  return (
    <section className="section page-section-anchor character-relation-section" id="character-relations">
      <div className="section__header">
        <div className="relation-header-title">
          <h2 className="section__title">{t("relation.title")}</h2>
          {graph && (
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
          )}
        </div>
        <div className="page__actions">
          <Button disabled={!graph || savePending || tableDirty || isFetching} onClick={() => setCleanDialogOpen(true)}>
            {t("relation.cleanLegacy")}
          </Button>
          <Button
            disabled={!owner || savePending || tableDirty || isFetching}
            onClick={() => void reload()}
          >
            {t("relation.reload")}
          </Button>
          <div className="relation-action-slot" ref={setActionsContainer} />
          <div className="relation-action-slot" ref={setSaveContainer} />
        </div>
      </div>
      <Dialog
        open={cleanDialogOpen}
        title={t("relation.cleanLegacy")}
        closeLabel={t("common.cancel")}
        dismissible={!savePending && !isFetching}
        trapFocus
        onClose={() => setCleanDialogOpen(false)}
        footer={
          <>
            <Button
              variant="primary"
              disabled={savePending || isFetching}
              onClick={() => {
                setCleanDialogOpen(false);
                void clean();
              }}
            >
              {t("common.confirm")}
            </Button>
            <Button disabled={savePending || isFetching} onClick={() => setCleanDialogOpen(false)}>
              {t("common.cancel")}
            </Button>
          </>
        }
      >
        <p>{t("relation.cleanLegacyWarning")}</p>
      </Dialog>
      {!owner && <p>{t("relation.saveFirst")}</p>}
      {owner && isLoading && <p role="status">{t("relation.loading")}</p>}
      {loadError && <p role="alert">{loadError}</p>}
      {saveError && <p role="alert">{saveError}</p>}
      {graph && (
        <>
          <div role="tabpanel" id="relation-graph-panel" aria-labelledby="relation-graph-tab" hidden={tab !== "graph"}>
            <CharacterGraphView
              active={tab === "graph"}
              graph={graph}
              disabled={savePending || tableDirty}
              actionsContainer={actionsContainer}
            />
          </div>
          <div role="tabpanel" id="relation-edit-panel" aria-labelledby="relation-edit-tab" hidden={tab !== "edit"}>
            <CharacterRelationTable
              key={JSON.stringify(graph)}
              graph={graph}
              pending={savePending}
              save={save}
              onDirty={setTableDirty}
              actionsContainer={actionsContainer}
              saveContainer={saveContainer}
              active={tab === "edit"}
            />
          </div>
        </>
      )}
    </section>
  );
}
