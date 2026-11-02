import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StoryCanvas } from "../../../features/story-generator/editor/StoryCanvas";
import { I18nProvider } from "../../../shared/i18n";
import type { StoryGraph } from "../../../shared/platform/storyPreviewTypes";

beforeEach(() => sessionStorage.clear());

it("keeps existing node positions when connections change and arranges only on request", () => {
  const graph: StoryGraph = {
    startNodeId: "a",
    nodes: [
      {
        id: "a",
        title: "Start",
        type: "free_chat_node",
        transitions: [
          { to: "b", when: "yes" },
          { to: "c", when: "no" },
        ],
      },
      { id: "b", title: "First ending", type: "ending_node" },
      { id: "c", title: "Second ending", type: "ending_node" },
    ],
  };
  const editor = (value: StoryGraph) => (
    <I18nProvider language="en">
      <StoryCanvas
        graph={value}
        selectedId="a"
        onSelect={vi.fn()}
        onConnect={vi.fn()}
        disabled={false}
        storageKey="canvas-test"
      />
    </I18nProvider>
  );
  const page = render(editor(graph));
  const position = () =>
    screen.getByRole("button", { name: "Ending First ending" }).closest("article")!.getAttribute("style");
  const before = position();
  const revised = {
    ...graph,
    nodes: graph.nodes.map((node) =>
      node.id === "a" ? { ...node, transitions: [{ to: "c", when: "continue" }] } : node,
    ),
  };
  page.rerender(editor(revised));
  expect(position()).toBe(before);
  fireEvent.click(screen.getByRole("button", { name: "Auto arrange" }));
  expect(position()).not.toBe(before);
  const arranged = position();
  page.unmount();
  render(editor(graph));
  expect(position()).toBe(arranged);
});
