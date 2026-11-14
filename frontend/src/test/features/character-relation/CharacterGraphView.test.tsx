import { state, renderRelationSection, seedRelationNode } from "./relationTestSetup";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { readGraphPositions } from "../../../features/character-relation/model/manageGraphLayout";
import { readPositions, savePositions } from "../../../features/character-relation/model/graphLayoutStorage";
import { CharacterGraphView } from "../../../features/character-relation/view/CharacterGraphView";
import type { CharacterRelationGraph } from "../../../shared/platform/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

describe("CharacterGraphView", () => {
  it("saves the previous owner's positions and restores the next owner when the graph changes", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const a: CharacterRelationGraph = { owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [] };
    const b: CharacterRelationGraph = { ...a, owner: "B" };
    const savedA = { A: { x: 25, y: 35 }, B: { x: 100, y: 120 } };
    const savedB = { A: { x: -75, y: 40 }, B: { x: 80, y: -90 } };
    savePositions("A", savedA);
    savePositions("B", savedB);
    const element = (graph: CharacterRelationGraph) => (
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <CharacterGraphView graph={graph} active={false} disabled={false} />
        </I18nProvider>
      </QueryClientProvider>
    );
    const view = render(element(a));
    expect(readGraphPositions(state.chart!)).toEqual(savedA);
    view.rerender(element(b));
    expect(readPositions("A")).toEqual(savedA);
    expect(readGraphPositions(state.chart!)).toEqual(savedB);
  });

  it("shows outgoing relationships of the person selected in the graph", async () => {
    await seedRelationNode("A", { key: "B" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: 7, content: "Friends" } },
    ]);
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    fireEvent.change(screen.getByLabelText("Select person"), { target: { value: "B" } });
    const links = (state.chart!.getOption().series as { links: { source: string; label: { show: boolean } }[] }[])[0]
      .links;
    expect(links.filter((link) => link.label.show).map((link) => link.source)).toEqual(["B"]);
  });

  it("fixes only the isolated node being dragged", async () => {
    await seedRelationNode("A", { key: "B" });
    await seedRelationNode("A", { key: "C" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "B", temperature: 7, content: "Friends" } },
    ]);
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    const point = readGraphPositions(chart).C;
    const start = chart.convertToPixel({ seriesIndex: 0 }, [point.x, point.y]);
    const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
    fireEvent.pointerDown(canvas, { clientX: start[0], clientY: start[1], button: 0 });
    fireEvent.pointerMove(canvas, { clientX: start[0] - 20, clientY: start[1] + 10 });
    const series = (chart.getOption().series as { data: { fixed: boolean }[] }[])[0];
    expect(series.data.map((node) => node.fixed)).toEqual([false, false, true]);
    fireEvent.pointerUp(canvas);
  });

  it("updates drag positions without rebuilding the chart series", async () => {
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    const point = readGraphPositions(chart).A;
    const start = chart.convertToPixel({ seriesIndex: 0 }, [point.x, point.y]);
    const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
    fireEvent.pointerDown(canvas, { clientX: start[0], clientY: start[1], button: 0 });
    fireEvent.pointerMove(canvas, { clientX: start[0] + 10, clientY: start[1] + 10 });
    const setOption = vi.spyOn(chart, "setOption");
    fireEvent.pointerMove(canvas, { clientX: start[0] + 20, clientY: start[1] + 20 });
    expect(setOption).not.toHaveBeenCalled();
    setOption.mockRestore();
    fireEvent.pointerUp(canvas);
  });

  it("shows outgoing relationship labels while hovering over a node", async () => {
    await seedRelationNode("A", { key: "B" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "B", temperature: 7, content: "Friends" } },
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: -2, content: "Distrust" } },
    ]);
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    act(() =>
      chart.trigger("mouseover", {
        type: "mouseover",
        componentType: "series",
        componentSubType: "graph",
        componentIndex: 0,
        name: "A",
        data: {},
        value: 0,
        $vars: [],
        dataType: "node",
        dataIndex: 0,
      }),
    );
    const links = (chart.getOption().series as { links: { source: string; label: { show: boolean } }[] }[])[0].links;
    expect(links.filter((link) => link.label.show).map((link) => link.source)).toEqual(["A"]);
  });

  it.each(["Reset layout", "Fit graph"])("keeps node positions stable on hover after %s", async (action) => {
    await seedRelationNode("A", { key: "B" });
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    fireEvent.click(screen.getByRole("button", { name: action }));
    const chart = state.chart!;
    const before = readGraphPositions(chart);
    act(() =>
      chart.trigger("mouseover", {
        type: "mouseover",
        componentType: "series",
        componentSubType: "graph",
        componentIndex: 0,
        name: "A",
        data: {},
        value: 0,
        $vars: [],
        dataType: "node",
        dataIndex: 0,
      }),
    );
    expect(readGraphPositions(chart)).toEqual(before);
  });

  it("converts pointer movement into the dragged node's graph coordinates", async () => {
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    const before = readGraphPositions(chart).A;
    const start = chart.convertToPixel({ seriesIndex: 0 }, [before.x, before.y]);
    const end = [start[0] + 40, start[1] + 25];
    const origin = chart.convertFromPixel({ seriesIndex: 0 }, start);
    const target = chart.convertFromPixel({ seriesIndex: 0 }, end);
    const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
    fireEvent.pointerDown(canvas, { clientX: start[0], clientY: start[1], button: 0 });
    fireEvent.pointerMove(canvas, { clientX: end[0], clientY: end[1] });
    const moved = readGraphPositions(chart).A;
    expect(moved.x).toBeCloseTo(before.x + target[0] - origin[0]);
    expect(moved.y).toBeCloseTo(before.y + target[1] - origin[1]);
    fireEvent.pointerUp(canvas);
  });

  it.each(["pointerUp", "pointerCancel", "lostPointerCapture"] as const)(
    "preserves the viewport when dragging ends with %s",
    async (finish) => {
      await seedRelationNode("A", { key: "B" });
      renderRelationSection();
      fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
      const chart = state.chart!;
      const point = readGraphPositions(chart).A;
      const start = chart.convertToPixel({ seriesIndex: 0 }, [point.x, point.y]);
      const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
      fireEvent.pointerDown(canvas, { clientX: start[0], clientY: start[1], button: 0 });
      fireEvent.pointerMove(canvas, { clientX: start[0] + 40, clientY: start[1] + 25 });
      const pixels = () =>
        Object.values(readGraphPositions(chart)).map((p) => chart.convertToPixel({ seriesIndex: 0 }, [p.x, p.y]));
      const before = pixels();
      fireEvent[finish](canvas);
      expect(pixels()).toEqual(before);
    },
  );

  it("ignores pointer movement after a drag has ended", async () => {
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    const point = readGraphPositions(chart).A;
    const start = chart.convertToPixel({ seriesIndex: 0 }, [point.x, point.y]);
    const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
    fireEvent.pointerDown(canvas, { clientX: start[0], clientY: start[1], button: 0 });
    fireEvent.pointerMove(canvas, { clientX: start[0] + 40, clientY: start[1] + 25 });
    fireEvent.pointerUp(canvas);
    const released = readGraphPositions(chart);
    fireEvent.pointerMove(canvas, { clientX: start[0] + 80, clientY: start[1] + 50 });
    expect(readGraphPositions(chart)).toEqual(released);
  });

  it("restores dragged node positions after the section is remounted", async () => {
    const view = renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    const point = readGraphPositions(chart).A;
    const start = chart.convertToPixel({ seriesIndex: 0 }, [point.x, point.y]);
    const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
    fireEvent.pointerDown(canvas, { clientX: start[0], clientY: start[1], button: 0 });
    fireEvent.pointerMove(canvas, { clientX: start[0] + 40, clientY: start[1] + 25 });
    fireEvent.pointerUp(canvas);
    const saved = readGraphPositions(chart);
    view.unmount();
    renderRelationSection();
    await screen.findByRole("tab", { name: "Relationship graph" });
    expect(readGraphPositions(state.chart!)).toEqual(saved);
  });

  it("preserves zoom when the selected person changes", async () => {
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    act(() => chart.setOption({ series: [{ id: "relationships", zoom: 2, center: [0, 0] }] }));
    fireEvent.change(screen.getByRole("combobox", { name: "Select person" }), { target: { value: "A" } });
    expect((chart.getOption().series as { zoom: number }[])[0].zoom).toBe(2);
  });

  it("starts dragging from the visible border of a zoomed node", async () => {
    renderRelationSection();
    fireEvent.click(await screen.findByRole("tab", { name: "Relationship graph" }));
    const chart = state.chart!;
    act(() => chart.setOption({ series: [{ id: "relationships", zoom: 2, center: [0, 0] }] }));
    const before = readGraphPositions(chart).A;
    const pixel = chart.convertToPixel({ seriesIndex: 0 }, [before.x, before.y]);
    const canvas = screen.getByLabelText("Relationship graph", { selector: "div.relation-graph-canvas" });
    // At zoom 2 this point is inside the visible radius but outside the original hit area.
    fireEvent.pointerDown(canvas, { clientX: pixel[0] + 40, clientY: pixel[1], button: 0 });
    fireEvent.pointerMove(canvas, { clientX: pixel[0] + 50, clientY: pixel[1] + 10 });
    expect(readGraphPositions(chart).A).not.toEqual(before);
    fireEvent.pointerUp(canvas);
  });
});
