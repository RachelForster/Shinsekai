import { renderRelationSection, seedRelationNode, state } from "./relationTestSetup";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

describe("CharacterRelationSection", () => {
  it("renders the relationship fields", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    renderRelationSection();
    expect(await screen.findByRole("textbox", { name: "Source 1" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Target 1" })).toBeInTheDocument();
    expect(screen.getByLabelText("Relationship 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Affection 1")).toBeInTheDocument();
    const headerActions = screen.getByRole("button", { name: "Add relationship" }).closest(".page__actions");
    expect(headerActions).not.toBeNull();
    expect(Array.from(headerActions!.querySelectorAll("button")).map((button) => button.textContent?.trim())).toEqual([
      "Clean up old data",
      "Reload",
      "Discard changes",
      "Add relationship",
      "Save",
    ]);
  });

  it("discards an unsaved relationship draft when the owner changes", async () => {
    await seedRelationNode("A", { key: "B" });
    const view = renderRelationSection();
    fireEvent.change(await screen.findByLabelText("Relationship 1"), { target: { value: "Draft" } });
    view.switchOwner("B");
    await waitFor(() => expect(screen.getByLabelText("Relationship 1")).toHaveValue(""));
  });

  it("hides the relationship table when the owner name is empty", () => {
    renderRelationSection("");
    expect(screen.queryByRole("textbox", { name: "Source 1" })).not.toBeInTheDocument();
  });

  it("does not clean old data when the confirmation is cancelled", async () => {
    await seedRelationNode("A", { key: "B" });
    const applyChanges = vi.spyOn(state.api!, "applyRelationChanges");
    renderRelationSection();
    const clean = await screen.findByRole("button", { name: "Clean up old data" });
    await waitFor(() => expect(clean).toBeEnabled());
    fireEvent.click(clean);
    const dialog = screen.getByRole("dialog", { name: "Clean up old data" });
    expect(applyChanges).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Cancel" }).at(-1)!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(applyChanges).not.toHaveBeenCalled();
    expect((await state.api!.getRelationGraph("A")).nodes).toEqual([{ key: "A" }, { key: "B" }]);
  });

  it("cleans old data only after confirmation", async () => {
    await seedRelationNode("A", { key: "B" });
    const applyChanges = vi.spyOn(state.api!, "applyRelationChanges");
    renderRelationSection();
    const clean = await screen.findByRole("button", { name: "Clean up old data" });
    await waitFor(() => expect(clean).toBeEnabled());
    fireEvent.click(clean);
    const dialog = screen.getByRole("dialog", { name: "Clean up old data" });
    expect(applyChanges).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(applyChanges).toHaveBeenCalledWith("A", [{ op: "delete_node", key: "B" }]));
    await waitFor(async () => expect((await state.api!.getRelationGraph("A")).nodes).toEqual([{ key: "A" }]));
  });

  it("disables cleanup while relationship edits are unsaved", async () => {
    renderRelationSection();
    const clean = await screen.findByRole("button", { name: "Clean up old data" });
    await waitFor(() => expect(clean).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Relationship 1"), { target: { value: "Draft" } });
    expect(clean).toBeDisabled();
    fireEvent.click(clean);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
