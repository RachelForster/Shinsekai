import type { CharacterRelationGraph } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";
import { useCharacterGraphController } from "../useCharacterGraphController";

interface CharacterGraphViewProps {
  graph: CharacterRelationGraph;
  disabled: boolean;
  active: boolean;
}

export function CharacterGraphView({ graph, disabled, active }: CharacterGraphViewProps) {
  const {
    t, selected, container, fitGraph, resetLayout, handleKeyDown, handlePersonSelection,
    handlePointerDown, handlePointerMove, handlePointerUp, cancelDrag,
    handleLostPointerCapture, handleClickCapture,
  } = useCharacterGraphController({ graph, disabled, active });

  return (
    <div className="relation-graph-view" onKeyDown={handleKeyDown}>
      <div className="page__actions">
        <Button onClick={fitGraph}>{t("relation.fitGraph")}</Button>
        <Button disabled={disabled} onClick={resetLayout}>
          {t("relation.resetLayout")}
        </Button>
      </div>
      <p>{t("relation.graphHint")}</p>
      <label className="relation-field">
        {t("relation.selectPerson")}
        <select value={selected} onChange={handlePersonSelection}>
          <option value="">—</option>
          {graph.nodes.map((node) => (
            <option key={node.key} value={node.key}>
              {node.key}
            </option>
          ))}
        </select>
      </label>
      <div
        ref={container}
        className="relation-graph-canvas"
        tabIndex={0}
        aria-label={t("relation.graphTab")}
        onPointerDownCapture={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={cancelDrag}
        onLostPointerCapture={handleLostPointerCapture}
        onClickCapture={handleClickCapture}
      />
    </div>
  );
}
