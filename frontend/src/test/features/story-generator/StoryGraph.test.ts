import { describe, expect, it } from "vitest";
import { layoutStoryGraph } from "../../../features/story-generator/graph/layout";
import { previewStoryGraph } from "../../../shared/platform/previewStoryGraph";
import { createHttpPlatform } from "../../../shared/platform/httpPlatform";
import { afterEach, vi } from "vitest";

describe("story graph layout", () => {
  it("lays out branches and cycles without duplicate positions", () => {
    const result = layoutStoryGraph(previewStoryGraph.graph!);
    expect(result.nodes).toHaveLength(4);
    expect(new Set(result.nodes.map((node) => `${node.x}-${node.y}`)).size).toBe(4);
    expect(result.nodes.find((node) => node.id === "clue")!.x).toBeGreaterThan(result.nodes[0].x);
  });
  it("keeps unreachable nodes visible and handles empty graphs", () => {
    const graph = {
      ...previewStoryGraph.graph!,
      nodes: [...previewStoryGraph.graph!.nodes, { id: "orphan", title: "孤立结局", type: "ending_node" as const }],
    };
    expect(layoutStoryGraph(graph).nodes).toHaveLength(5);
    expect(layoutStoryGraph({ nodes: [], startNodeId: "" }).nodes).toEqual([]);
  });
});

describe("story preview and session transport", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("uses task IDs for previews and passes the draft path as JSON for launch", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => previewStoryGraph });
    vi.stubGlobal("fetch", fetch);
    const platform = createHttpPlatform("http://localhost:8000");
    await platform.story.getPreview("task 1");
    expect(String(fetch.mock.calls[0][0])).toContain("/api/story/generation/task%201/preview");
    await platform.story.startSession("data/stories/example/draft.json");
    expect(String(fetch.mock.calls[1][0])).toContain("/api/story/start");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ storyPath: "data/stories/example/draft.json" });
    await platform.story.list();
    expect(String(fetch.mock.calls[2][0])).toContain("/api/story/library");
    await platform.story.prepareLaunch("data/stories/example/draft.json", "data/chat_history/saved");
    expect(String(fetch.mock.calls[3][0])).toContain("/api/story/launch-payload");
    expect(JSON.parse(fetch.mock.calls[3][1].body)).toEqual({
      storyPath: "data/stories/example/draft.json",
      historyPath: "data/chat_history/saved",
    });
  });
});
