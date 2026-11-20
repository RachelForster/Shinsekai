import { renderRelationSection, seedRelationNode } from "./relationTestSetup";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("CharacterRelationSection", () => {
  it("renders the relationship fields", async () => {
    await seedRelationNode("A", { key: "Innkeeper" });
    renderRelationSection();
    expect(await screen.findByRole("combobox", { name: "Source 1" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Target 1" })).toBeInTheDocument();
    expect(screen.getByLabelText("Relationship 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Affection 1")).toBeInTheDocument();
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
    expect(screen.queryByRole("combobox", { name: "Source 1" })).not.toBeInTheDocument();
  });
});
