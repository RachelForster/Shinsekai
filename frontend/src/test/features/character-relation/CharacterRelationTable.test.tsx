import { state, renderRelationSection, seedRelationNode } from "./relationTestSetup";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

describe("CharacterRelationTable", () => {
  it("saves a directed relationship in the current owner graph", async () => {
    await seedRelationNode("A", { key: "B" });
    renderRelationSection();
    await screen.findByLabelText("Source 1");
    expect(screen.getByLabelText("Source 1")).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Source 1"), { target: { value: "B" } });
    fireEvent.change(screen.getByLabelText("Target 1"), { target: { value: "A" } });
    fireEvent.change(screen.getByLabelText("Relationship 1"), { target: { value: "Avoids me" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: /1$/ }), { target: { value: "-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    const graph = await state.api!.getRelationGraph("A");
    expect(graph.edges).toContainEqual(expect.objectContaining({ source: "B", target: "A", temperature: -2 }));
    expect((await state.api!.getRelationGraph("B")).edges).toEqual([]);
  });

  it("restores a relationship row when deletion is cancelled", async () => {
    await seedRelationNode("A", { key: "B" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "B", temperature: 7, content: "Friends" } },
    ]);
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "Delete relationship 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByLabelText("Source 1")).toHaveValue("A");
    expect(screen.getByLabelText("Relationship 1")).toHaveValue("Friends");
  });

  it("deletes only the selected directed relationship on save", async () => {
    await seedRelationNode("A", { key: "B" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "B", temperature: 7, content: "Friends" } },
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: -2, content: "Distrust" } },
    ]);
    renderRelationSection();
    fireEvent.click(await screen.findByRole("button", { name: "Delete relationship 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect((await state.api!.getRelationGraph("A")).edges).toEqual([
      { source: "B", target: "A", temperature: -2, content: "Distrust" },
    ]);
  });

  it("preserves relationship text when saving a temperature change", async () => {
    await seedRelationNode("A", { key: "B" });
    await state.api!.applyRelationChanges("A", [
      { op: "upsert_edge", edge: { source: "A", target: "B", temperature: 7, content: "Shared journey" } },
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: -2, content: "Shared journey" } },
    ]);
    renderRelationSection();
    fireEvent.change(await screen.findByRole("spinbutton", { name: /1$/ }), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect((await state.api!.getRelationGraph("A")).edges).toContainEqual(
      expect.objectContaining({ source: "B", target: "A", content: "Shared journey" }),
    );
  });

  it("retains relationship text after a failed save", async () => {
    await seedRelationNode("A", { key: "B" });
    renderRelationSection();
    fireEvent.change(await screen.findByLabelText("Source 1"), { target: { value: "A" } });
    fireEvent.change(screen.getByLabelText("Target 1"), { target: { value: "B" } });
    fireEvent.change(screen.getByLabelText("Relationship 1"), { target: { value: "Draft" } });
    vi.spyOn(state.api!, "applyRelationChanges").mockRejectedValueOnce(new Error("Unable to save graph"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save graph");
    expect(screen.getByLabelText("Relationship 1")).toHaveValue("Draft");
    expect(screen.getByRole("button", { name: "Reload" })).toBeDisabled();
  });
});
