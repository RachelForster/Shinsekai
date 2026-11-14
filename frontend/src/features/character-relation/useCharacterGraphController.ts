import {
  createGraphSelection,
  selectGraphNode,
  hoverGraphNode,
  clearGraphSelection,
  activeGraphNode,
} from "./model/graphSelection";
import { useQuery } from "@tanstack/react-query";
import type { ChangeEvent, KeyboardEvent, MouseEvent, PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { useI18n } from "../../shared/i18n";
import type { CharacterRelationGraph } from "../../shared/platform/types";
import { graphSeries } from "./view/buildGraphSeries";
import { usePreparingGraphAvatars } from "./preparingGraphAvatars";
import { readGraphPositions, installGraphBounds, moveGraphNode } from "./model/manageGraphLayout";
import { createGraphLayout, reconcileGraphLayout, resetGraphLayout, syncGraphLayout } from "./model/graphLayout";
import { readPositions, savePositions } from "./model/graphLayoutStorage";
import { readGraphTheme, type GraphTheme } from "./model/graphTheme";
import {
  createGraphChart,
  renderGraphChart,
  fitGraphChart,
  type GraphChartModel,
  hitGraphNode,
  graphDragPosition,
} from "./model/graphChart";
import { beginGraphDrag, advanceGraphDrag, type GraphDragModel } from "./model/graphDrag";

type ChartEvent = { dataType?: string; dataIndex?: number };
interface CharacterGraphControllerProps {
  graph: CharacterRelationGraph;
  disabled: boolean;
  active: boolean;
}

export function useCharacterGraphController({ graph, disabled, active }: CharacterGraphControllerProps) {
  const { t } = useI18n();
  const { data: characters } = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters, retry: false });
  const container = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<GraphChartModel>();
  const theme = useRef<GraphTheme>();
  const fitted = useRef(false);
  const selection = useRef(createGraphSelection());
  const [, refreshSelection] = useState(0);
  const setSelected = (key: string) => {
    selectGraphNode(selection.current, key);
    refreshSelection((value) => value + 1);
  };
  const avatars = usePreparingGraphAvatars(graph.nodes, characters);
  const layout = useRef(createGraphLayout(graph, readPositions(graph.owner)));
  const latestState = useRef({ graph, t, characters, avatars });
  latestState.current = { graph, t, characters, avatars };
  const dragState = useRef<GraphDragModel | null>(null);
  const suppressNextClick = useRef(false);
  const renderGraph = () => {
    const chart = chartInstance.current;
    if (!chart || !container.current) return;
    const activeDrag = dragState.current;
    const simulating = Boolean(activeDrag?.moved);
    const palette = theme.current ?? (theme.current = readGraphTheme(container.current));
    const series = graphSeries({
      graph: latestState.current.graph,
      positions: layout.current.defaults,
      activeNodeKey: activeGraphNode(selection.current),
      emptyRelationLabel: latestState.current.t("relation.noEntry"),
      textColor: palette.text,
      backgroundColor: palette.background,
      fixedKeys: new Set(
        activeDrag?.moved ? [activeDrag.key] : latestState.current.graph.nodes.map((node) => node.key),
      ),
      theme: palette,
      edgeLengths: layout.current.edgeLengths,
      characters: latestState.current.characters,
      avatars: latestState.current.avatars,
      selectedNodeKey: selection.current.selectedKey,
    });
    renderGraphChart(chart, series, layout.current.positions, simulating);
  };
  const clearSelection = () => {
    clearGraphSelection(selection.current);
    setSelected("");
    renderGraph();
  };
  const syncPositions = () => {
    if (!chartInstance.current) return;
    syncGraphLayout(layout.current, readGraphPositions(chartInstance.current), dragState.current?.key);
  };
  const persistPositions = (owner = latestState.current.graph.owner) => {
    syncPositions();
    savePositions(owner, layout.current.positions);
  };
  const fitGraph = () => {
    const chart = chartInstance.current;
    if (!chart) return;
    syncPositions();
    fitGraphChart(chart, layout.current.positions, Boolean(dragState.current?.moved));
  };
  const resizeChart = () => {
    const element = container.current;
    const chart = chartInstance.current;
    if (!element || !chart || !element.clientWidth || !element.clientHeight) return;
    chart.resize({ width: element.clientWidth, height: element.clientHeight });
    if (dragState.current?.moved) installGraphBounds(chart);
  };
  useEffect(() => {
    if (!container.current) return;
    const owner = graph.owner;
    layout.current = createGraphLayout(graph, readPositions(owner));
    fitted.current = false;
    dragState.current = null;
    clearGraphSelection(selection.current);
    setSelected("");
    const chart = createGraphChart(container.current);
    chartInstance.current = chart;
    theme.current = readGraphTheme(container.current);
    chart.on("rendered", syncPositions);
    chart.on("mouseover", (event: ChartEvent) => {
      if (dragState.current || event.dataType !== "node") return;
      hoverGraphNode(selection.current, latestState.current.graph.nodes[event.dataIndex ?? -1]?.key ?? "");
      renderGraph();
    });
    chart.on("mouseout", () => {
      if (!dragState.current) {
        hoverGraphNode(selection.current, "");
        renderGraph();
      }
    });
    chart.on("click", (event: ChartEvent) => {
      if (suppressNextClick.current) return;
      if (event.dataType === "node") {
        setSelected(latestState.current.graph.nodes[event.dataIndex ?? -1]?.key ?? "");
        renderGraph();
      }
    });
    chart.getZr().on("click", (event) => {
      if (!event.target && !suppressNextClick.current) clearSelection();
    });
    const observer = new ResizeObserver(resizeChart);
    observer.observe(container.current);
    const refreshTheme = () => {
      if (!container.current) return;
      syncPositions();
      theme.current = readGraphTheme(container.current);
      renderGraph();
    };
    const themeObserver = new MutationObserver(refreshTheme);
    for (const element of [document.documentElement, document.body]) {
      themeObserver.observe(element, { attributes: true, attributeFilter: ["class", "style", "data-color-scheme"] });
    }
    const colorScheme = window.matchMedia?.("(prefers-color-scheme: dark)");
    colorScheme?.addEventListener("change", refreshTheme);
    return () => {
      observer.disconnect();
      themeObserver.disconnect();
      colorScheme?.removeEventListener("change", refreshTheme);
      persistPositions(owner);
      chart.dispose();
      chartInstance.current = undefined;
    };
  }, [graph.owner]);
  useEffect(() => {
    reconcileGraphLayout(layout.current, graph);
    if (selection.current.selectedKey && !graph.nodes.some((node) => node.key === selection.current.selectedKey))
      clearSelection();
    renderGraph();
  }, [graph, t, characters, avatars]);
  useEffect(() => {
    if (active) {
      resizeChart();
      if (!fitted.current) {
        fitGraph();
        fitted.current = true;
      }
    }
  }, [active, graph.owner]);
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === "Escape") clearSelection();
  };

  const resetLayout = (): void => {
    resetGraphLayout(layout.current, graph);
    renderGraph();
    persistPositions();
    fitGraph();
  };

  const handlePersonSelection = (e: ChangeEvent<HTMLSelectElement>): void => {
    hoverGraphNode(selection.current, "");
    setSelected(e.target.value);
    renderGraph();
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>): void => {
    suppressNextClick.current = false;
    const chart = chartInstance.current;
    if (!chart || disabled || event.button !== 0) return;
    syncPositions();
    const rect = event.currentTarget.getBoundingClientRect();
    const pixel = [
      event.clientX - rect.left - event.currentTarget.clientLeft,
      event.clientY - rect.top - event.currentTarget.clientTop,
    ];
    const node = hitGraphNode(chart, graph.nodes, layout.current.positions, pixel);
    if (!node) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragState.current = beginGraphDrag(node.key, event.pointerId, layout.current.positions[node.key], pixel);
    suppressNextClick.current = false;
    renderGraph();
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const activeDrag = dragState.current;
    const chart = chartInstance.current;
    if (!activeDrag || activeDrag.pointerId !== event.pointerId || !chart) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const pixel = [
      event.clientX - rect.left - event.currentTarget.clientLeft,
      event.clientY - rect.top - event.currentTarget.clientTop,
    ];
    const movement = advanceGraphDrag(activeDrag, event.pointerId, pixel);
    if (!movement) return;
    const { starting } = movement;
    const point = graphDragPosition(chart, activeDrag, pixel);
    syncPositions();
    layout.current.positions[activeDrag.key] = point;
    if (starting) renderGraph();
    moveGraphNode(chart, activeDrag.key, layout.current.positions[activeDrag.key]);
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const activeDrag = dragState.current;
    if (!activeDrag || activeDrag.pointerId !== event.pointerId) return;
    syncPositions();
    dragState.current = null;
    suppressNextClick.current = true;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (!activeDrag.moved) {
      setSelected(activeDrag.key);
    }
    renderGraph();
    persistPositions();
  };

  const cancelDrag = (): void => {
    syncPositions();
    dragState.current = null;
    renderGraph();
    persistPositions();
  };

  const handleLostPointerCapture = (): void => {
    if (dragState.current) cancelDrag();
  };

  const handleClickCapture = (event: MouseEvent<HTMLDivElement>): void => {
    if (suppressNextClick.current) {
      event.stopPropagation();
      suppressNextClick.current = false;
    }
  };

  return {
    t,
    selected: selection.current.selectedKey,
    container,
    fitGraph,
    resetLayout,
    handleKeyDown,
    handlePersonSelection,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
    cancelDrag,
    handleLostPointerCapture,
    handleClickCapture,
  };
}
