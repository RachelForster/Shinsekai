import { state, characters, renderRelationSection, seedRelationNode } from "./relationTestSetup";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

describe("CharacterRelationNodeEditor", () => {
  it("saves staged custom and library nodes in one request", async () => {
    renderRelationSection();
    await screen.findByRole("button", { name: "A" });
    const save = vi.spyOn(state.api!, "applyRelationChanges");
    expect(screen.getByRole("region", { name: "Existing characters" })).toBeInTheDocument();
    const custom = screen.getByRole("region", { name: "Custom characters" });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: " Innkeeper " } });
    fireEvent.click(within(custom).getByRole("button", { name: "Add" }));
    expect(within(custom).getByText("Innkeeper")).toBeInTheDocument();
    expect((await state.api!.getRelationGraph("A")).nodes).toEqual([{ key: "A" }]);
    save.mockClear();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "innkeeper" } });
    expect(within(custom).getByRole("button", { name: "Add" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /Select all/i }));
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect(save).toHaveBeenCalledTimes(1);
    expect((await state.api!.getRelationGraph("A")).nodes.map((node) => node.key)).toEqual(
      expect.arrayContaining(["A", "B", "C", "Innkeeper"]),
    );
    expect(await state.platform!.characters.list()).not.toContainEqual(expect.objectContaining({ name: "Innkeeper" }));
  });

  it("removes a saved custom node and its incident edges", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    await seedRelationNode("B", { key: "Innkeeper" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "Innkeeper", temperature: 4, content: "Shared journey" } },
      { op: "upsert_edge", edge: { source: "Innkeeper", target: "A", temperature: -2, content: "Shared journey" } },
    ]);
    await state.api!.applyRelationChanges("B", [
      { op: "upsert_edge", edge: { source: "B", target: "Innkeeper", temperature: 3, content: "Shared journey" } },
    ]);
    renderRelationSection();
    let remove = await screen.findByRole("button", { name: "Delete person: Innkeeper" });
    expect(screen.queryByRole("button", { name: "Delete person: A" })).not.toBeInTheDocument();
    fireEvent.click(remove);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect((await state.api!.getRelationGraph("A")).edges).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Cancel: Character relationships" }));
    remove = screen.getByRole("button", { name: "Delete person: Innkeeper" });
    fireEvent.click(remove);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    const graph = await state.api!.getRelationGraph("A");
    expect(graph.nodes).toEqual([{ key: "A" }]);
    expect(graph.edges).toEqual([]);
    expect(
      within(screen.getByLabelText("Target 1")).queryByRole("option", { name: "Innkeeper" }),
    ).not.toBeInTheDocument();
    expect((await state.api!.getRelationGraph("B")).edges).toHaveLength(1);
  });

  it("retries a failed save with the staged node deletion", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "Delete person: Innkeeper" }));
    vi.spyOn(state.api!, "applyRelationChanges").mockRejectedValueOnce(new Error("Unable to save graph"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save graph");
    expect(screen.queryByRole("button", { name: "Delete person: Innkeeper" })).not.toBeInTheDocument();
    expect((await state.api!.getRelationGraph("A")).nodes).toContainEqual({ key: "Innkeeper" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect((await state.api!.getRelationGraph("A")).nodes).toEqual([{ key: "A" }]);
  });

  it("clears a save error when reloading after cancelling the failed draft", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "Delete person: Innkeeper" }));
    vi.spyOn(state.api!, "applyRelationChanges").mockRejectedValueOnce(new Error("Unable to save graph"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save graph");
    fireEvent.click(screen.getByRole("button", { name: "Cancel: Character relationships" }));
    const fetchGraph = vi.spyOn(state.api!, "getRelationGraph");
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(fetchGraph).toHaveBeenCalledWith("A");
    expect(await screen.findByRole("button", { name: "Delete person: Innkeeper" })).toBeInTheDocument();
  });

  it("discards an unsaved node addition without submitting changes", async () => {
    renderRelationSection();
    await screen.findByRole("button", { name: "A" });
    const save = vi.spyOn(state.api!, "applyRelationChanges");
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "New person" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete person: New person" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });

  it("applies library removal, custom removal and custom creation in a single batch", async () => {
    await seedRelationNode("A", { key: "B" });
    await seedRelationNode("A", { key: "Innkeeper" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "B", target: "Innkeeper", temperature: 4, content: "Shared journey" } },
    ]);
    renderRelationSection();
    const remove = await screen.findByRole("button", { name: "Delete person: Innkeeper" });
    const save = vi.spyOn(state.api!, "applyRelationChanges");
    fireEvent.click(screen.getByRole("button", { name: "B" }));
    fireEvent.click(remove);
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "New person" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(save).not.toHaveBeenCalled();
    expect((await state.api!.getRelationGraph("A")).nodes).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("A", [
      { op: "delete_node", key: "B" },
      { op: "delete_node", key: "Innkeeper" },
      { op: "add_node", node: { key: "New person" } },
    ]);
  });

  it("retries a failed save with the staged library selection", async () => {
    await seedRelationNode("A", { key: "B" });
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "C" }));
    expect(screen.getByRole("button", { name: "B" })).toHaveAttribute("aria-pressed", "true");
    vi.spyOn(state.api!, "applyRelationChanges").mockRejectedValueOnce(new Error("Save failed"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed");
    expect(screen.getByRole("button", { name: "C" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect((await state.api!.getRelationGraph("A")).nodes.map((n) => n.key)).toEqual(["A", "B", "C"]);
  });

  it("removes a deselected node and every incident relationship on save", async () => {
    await seedRelationNode("A", { key: "B" });
    await seedRelationNode("A", { key: "C" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "B", temperature: 7, content: "Outgoing" } },
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: -2, content: "Incoming" } },
      { op: "upsert_edge", edge: { source: "C", target: "B", temperature: 1, content: "Third party" } },
    ]);
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "B" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    const graph = await state.api!.getRelationGraph("A");
    expect({ nodes: graph.nodes, edges: graph.edges }).toEqual({ nodes: [{ key: "A" }, { key: "C" }], edges: [] });
  });

  it("does not modify another owner's graph when a library node is deselected", async () => {
    await seedRelationNode("A", { key: "B" });
    await seedRelationNode("B", { key: "A" });
    await state.api!.applyRelationChanges("B", [
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: 4, content: "Friends" } },
    ]);
    const before = await state.api!.getRelationGraph("B");
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "B" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect(await state.api!.getRelationGraph("B")).toEqual(before);
  });
});
