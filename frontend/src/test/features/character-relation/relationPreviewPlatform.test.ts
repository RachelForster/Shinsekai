import { state, characters, seedRelationNode } from "./relationTestSetup";
import { describe, expect, it } from "vitest";

describe("relationPreviewPlatform", () => {
  it("keeps graph nodes independent of library briefs", async () => {
    const b = characters.find((c) => c.name === "B")!;
    await seedRelationNode("A", { key: "B" });
    await seedRelationNode("C", { key: "B" });
    await state.platform!.characters.save({ ...b, character_brief: "Changed in library" });
    expect((await state.api!.getRelationGraph("A")).nodes[1]).toEqual({ key: "B" });
    expect((await state.api!.getRelationGraph("C")).nodes[1]).toEqual({ key: "B" });
  });

  it("rolls back the whole batch when an edge endpoint is missing", async () => {
    await seedRelationNode("A", { key: "B" });
    const before = await state.api!.getRelationGraph("A");
    await expect(
      state.api!.applyRelationChanges("A", [
        { op: "add_node", node: { key: "D" } },
        { op: "upsert_edge", edge: { source: "D", target: "Missing", temperature: 0, content: "" } },
      ]),
    ).rejects.toThrow("Invalid relationship");
    expect(await state.api!.getRelationGraph("A")).toEqual(before);
  });
});
