import { state, characters, renderRelationSection, seedRelationNode } from "./relationTestSetup";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("CharacterRelationSection", () => {
  it("renders the relationship table columns", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    renderRelationSection();
    const table = await screen.findByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["#", "Source", "Target", "Relationship", "Affection"]);
  });

  it("disables node deletion while a relationship draft is dirty", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    renderRelationSection();
    const remove = await screen.findByRole("button", { name: "Delete person: Innkeeper" });
    fireEvent.change(screen.getByLabelText("Relationship 1"), { target: { value: "Draft" } });
    expect(remove).toBeDisabled();
  });

  it("disables relationship editing while a node addition is staged", async () => {
    renderRelationSection();
    await screen.findByRole("button", { name: "A" });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "New person" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByLabelText("Relationship 1")).toBeDisabled();
  });

  it("isolates unsaved custom nodes when switching owners", async () => {
    const view = renderRelationSection();
    await screen.findByRole("button", { name: "A" });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Unsaved person" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    view.switchOwner("B");
    await waitFor(() => expect(screen.getByRole("button", { name: "B" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByRole("button", { name: "Delete person: Unsaved person" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect((await state.api!.getRelationGraph("A")).nodes).toEqual([{ key: "A" }]);
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
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("handles library errors without blocking relationship editing", async () => {
    await seedRelationNode("A", { key: "B" });
    state.listCharacters.mockRejectedValueOnce(new Error("Library unavailable")).mockResolvedValue([characters[0]]);
    renderRelationSection();
    expect(await screen.findByRole("alert")).toHaveTextContent("Library unavailable");
    expect(screen.getByLabelText("Target 1")).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("button", { name: "A" });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect((await state.api!.getRelationGraph("A")).nodes[1]).toEqual({ key: "B" });
  });
});
