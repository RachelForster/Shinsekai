import { state, renderRelationSection, seedRelationNode } from "./relationTestSetup";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

describe("CharacterRelationTable", () => {
  it("opens the person picker on focus and ArrowDown, and closes it on Escape", async () => {
    renderRelationSection();
    const input = await screen.findByRole("textbox", { name: "Target 1" });
    const picker = screen.getByRole("combobox", { name: "Target 1 ▾" });
    await waitFor(() => expect(picker).toBeEnabled());
    fireEvent.focus(input);
    expect(picker).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("option", { name: "B" })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(picker).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(picker).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("option", { name: "B" }));
    expect(input).toHaveValue("B");
    expect(picker).toHaveAttribute("aria-expanded", "false");
  });

  it("places the person picker above the input near the bottom of the viewport", async () => {
    renderRelationSection();
    const input = await screen.findByRole("textbox", { name: "Target 1" });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Target 1 ▾" })).toBeEnabled());
    const root = input.parentElement!;
    const bottom = window.innerHeight - 10;
    vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
      x: 20,
      y: bottom - 30,
      left: 20,
      right: 220,
      top: bottom - 30,
      bottom,
      width: 200,
      height: 30,
      toJSON: () => ({}),
    });
    fireEvent.focus(input);
    const list = screen.getByRole("listbox");
    expect(parseFloat(list.style.top)).toBeLessThan(bottom - 30);
  });

  it("offers library characters and saves a typed person with the relationship", async () => {
    renderRelationSection();
    const source = await screen.findByRole("textbox", { name: "Source 1" });
    expect(source).toHaveValue("A");
    expect(source).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Target 1 ▾" })).toBeEnabled());
    fireEvent.click(screen.getByRole("combobox", { name: "Target 1 ▾" }));
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    fireEvent.click(screen.getByRole("option", { name: "B" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Target 1" }), { target: { value: "New person" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    const graph = await state.api!.getRelationGraph("A");
    expect(graph.nodes).toEqual(expect.arrayContaining([{ key: "A" }, { key: "New person" }]));
    expect(graph.edges).toContainEqual(expect.objectContaining({ source: "A", target: "New person" }));
  });
  it("saves a directed relationship in the current owner graph", async () => {
    await seedRelationNode("A", { key: "B" });
    renderRelationSection();
    await screen.findByLabelText("Source 1");
    expect(screen.getByLabelText("Source 1")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Swap source and target 1" }));
    fireEvent.change(screen.getByLabelText("Source 1"), { target: { value: "B" } });
    expect(screen.getByLabelText("Target 1")).toBeDisabled();
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
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
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
    await screen.findByLabelText("Source 1");
    fireEvent.change(screen.getByLabelText("Target 1"), { target: { value: "B" } });
    fireEvent.change(screen.getByLabelText("Relationship 1"), { target: { value: "Draft" } });
    vi.spyOn(state.api!, "applyRelationChanges").mockRejectedValueOnce(new Error("Unable to save graph"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save graph");
    expect(screen.getByLabelText("Relationship 1")).toHaveValue("Draft");
    expect(screen.getByRole("button", { name: "Reload" })).toBeDisabled();
  });

  it("defaults new rows to the owner and swaps endpoints", async () => {
    renderRelationSection();
    await screen.findByLabelText("Source 1");
    fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));
    expect(screen.getByLabelText("Source 2")).toHaveValue("A");
    expect(screen.getByLabelText("Source 2")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Target 2"), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "Swap source and target 2" }));
    expect(screen.getByLabelText("Source 2")).toHaveValue("B");
    expect(screen.getByLabelText("Target 2")).toHaveValue("A");
    expect(screen.getByLabelText("Target 2")).toBeDisabled();
  });
});
