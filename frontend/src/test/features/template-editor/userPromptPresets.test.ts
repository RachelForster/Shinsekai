import { describe, expect, it } from "vitest";

import {
  composeScenarioWithPresets,
  normalizeUserPromptPresetLibrary,
  reorderPresetIds,
  reorderPresetIdsById,
  resolveSelectedPresets,
  toAppliedPresets,
} from "../../../features/template-editor/userPromptPresets";

describe("userPromptPresets helpers", () => {
  it("normalizes groups and presets without duplicating names or dropping preset groups", () => {
    const normalized = normalizeUserPromptPresetLibrary({
      groups: ["  文风 ", "文风", ""],
      presets: [
        { id: "p1", name: "  轻小说  ", group: "文风", color: "#5b8def", content: "A\r\nB" },
        { id: "p2", name: "禁代笔", group: "规则", content: "Do not speak for player." },
        { id: "p1", name: "Duplicate", group: "", content: "ignored" },
        { id: "p3", name: "   ", group: "", content: "ignored" },
      ],
    });

    expect(normalized).toEqual({
      groups: ["文风", "规则"],
      presets: [
        { id: "p1", name: "轻小说", group: "文风", color: "#5b8def", content: "A\nB" },
        { id: "p2", name: "禁代笔", group: "规则", content: "Do not speak for player." },
      ],
    });
  });

  it("appends selected presets non-destructively in selected order", () => {
    const base = "Evening walk along the canal.";
    const p1 = { id: "p1", name: "Tone", group: "", content: "Use calm light novel pacing." };
    const p2 = { id: "p2", name: "Rule", group: "", content: "Keep responses under 3 paragraphs." };

    expect(composeScenarioWithPresets(base, [])).toBe(base);
    expect(composeScenarioWithPresets(base, [p1, p2])).toBe(
      "Evening walk along the canal.\n\nUse calm light novel pacing.\n\nKeep responses under 3 paragraphs.",
    );
    expect(composeScenarioWithPresets("   ", [p1, p2])).toBe(
      "Use calm light novel pacing.\n\nKeep responses under 3 paragraphs.",
    );
    expect(composeScenarioWithPresets(base, [p2])).toBe(
      "Evening walk along the canal.\n\nKeep responses under 3 paragraphs.",
    );
  });

  it("prefers saved applied snapshots over edited live presets and tracks deleted status accurately", () => {
    const library = {
      groups: ["Tone", "Rules"],
      presets: [
        { id: "p1", name: "Live Tone", group: "Tone", color: "#5b8def", content: "Updated live text" },
        { id: "p3", name: "Fresh Rule", group: "Rules", color: "#46b98b", content: "Newly added text" },
      ],
    };
    const fallback = [
      { id: "p1", name: "Old Tone", group: "Tone", content: "Old text" },
      { id: "p2", name: "Deleted Rule", group: "Rules", content: "Snapshot text" },
    ];

    const resolved = resolveSelectedPresets(["p1", "p2", "p3", "missing"], library, fallback);
    expect(resolved).toEqual([
      {
        id: "p1",
        name: "Old Tone",
        group: "Tone",
        color: "#5b8def",
        content: "Old text",
        isDeleted: false,
      },
      {
        id: "p2",
        name: "Deleted Rule",
        group: "Rules",
        content: "Snapshot text",
        isDeleted: true,
      },
      {
        id: "p3",
        name: "Fresh Rule",
        group: "Rules",
        color: "#46b98b",
        content: "Newly added text",
        isDeleted: false,
      },
    ]);
    expect(toAppliedPresets(resolved)).toEqual([
      { id: "p1", name: "Old Tone", group: "Tone", color: "#5b8def", content: "Old text" },
      { id: "p2", name: "Deleted Rule", group: "Rules", content: "Snapshot text" },
      { id: "p3", name: "Fresh Rule", group: "Rules", color: "#46b98b", content: "Newly added text" },
    ]);

    const whilePending = resolveSelectedPresets(["p1", "p2"], { groups: [], presets: [] }, fallback, {
      libraryLoaded: false,
    });
    expect(whilePending.every((item) => item.isDeleted === false)).toBe(true);
  });

  it("reorders preset ids cleanly by index and by id", () => {
    expect(reorderPresetIds(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
    expect(reorderPresetIds(["a", "b", "c"], -1, 1)).toEqual(["a", "b", "c"]);
    expect(reorderPresetIdsById(["a", "b", "c"], "c", "a")).toEqual(["c", "a", "b"]);
  });
});
