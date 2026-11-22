import type { CharacterRelationGraph } from "../../../shared/platform/types";
import { Button } from "../../../shared/ui";
import { useCharacterGraphController } from "../useCharacterGraphController";
import { createPortal } from "react-dom";

interface CharacterGraphViewProps {
  graph: CharacterRelationGraph;
  disabled: boolean;
  active: boolean;
  actionsContainer: HTMLElement | null;
}

export function CharacterGraphView({ graph, disabled, active, actionsContainer }: CharacterGraphViewProps) {
  const {
    t,
    container,
    fitGraph,
    resetLayout,
    handleKeyDown,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
    cancelDrag,
    handleLostPointerCapture,
    handleClickCapture,
  } = useCharacterGraphController({ graph, disabled, active });

  return (
    <div className="relation-graph-view" onKeyDown={handleKeyDown}>
      {active &&
        actionsContainer &&
        createPortal(
          <>
            <Button onClick={fitGraph}>{t("relation.fitGraph")}</Button>
            <Button disabled={disabled} onClick={resetLayout}>
              {t("relation.resetLayout")}
            </Button>
          </>,
          actionsContainer,
        )}
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
