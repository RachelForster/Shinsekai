import { cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, vi } from "vitest";
import { CharacterRelationSection } from "../../../features/character-relation/view/CharacterRelationSection";
import { createBrowserPreviewPlatform } from "../../../shared/platform/browserPreviewPlatform";
import type { RelationNode, RelationRequest } from "../../../shared/platform/types";
import type { Character } from "../../../shared/platform/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

vi.mock("echarts/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("echarts/core")>();
  const { SVGRenderer } = await import("echarts/renderers");
  actual.use([SVGRenderer]);
  return {
    ...actual,
    init: () => {
      state.chart = actual.init(null, undefined, { renderer: "svg", ssr: true, width: 640, height: 560 });
      const resize = state.chart.resize.bind(state.chart);
      state.chart.resize = () => resize({ width: 640, height: 560 });
      return state.chart;
    },
  };
});
vi.stubGlobal(
  "PointerEvent",
  class extends MouseEvent {
    pointerId = 1;
  },
);
HTMLElement.prototype.setPointerCapture = vi.fn();
HTMLElement.prototype.releasePointerCapture = vi.fn();
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    disconnect() {}
  },
);

const state = vi.hoisted(() => ({
  chart: null as import("echarts/core").EChartsType | null,
  api: null as ReturnType<typeof createBrowserPreviewPlatform>["characterRelation"] | null,
  platform: null as ReturnType<typeof createBrowserPreviewPlatform> | null,
  listCharacters: vi.fn(),
}));
vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => state.listCharacters(),
}));
vi.mock("../../../entities/character-relation/repository", () => ({
  relationQueryKey: ["character-relations"],
  getCharacterRelationGraph: (owner: string) => state.api!.getRelationGraph(owner),
  applyCharacterRelationChanges: (owner: string, operations: RelationRequest[]) =>
    state.api!.applyRelationChanges(owner, operations),
}));
export const characters: Character[] = ["A", "B", "C"].map((name) => ({
  avatar_type: "static",
  avatars: {},
  color: "#123abc",
  sprite_prefix: name,
  sprites: [],
  sprite_scale: 1,
  emotion_tags: "",
  speech_speed: 1,
  speech_volume: 1,
  pronunciation_map: {},
  name,
  character_brief: `Brief ${name}`,
  character_setting: `Setting ${name}`,
}));
beforeEach(async () => {
  localStorage.clear();
  const platform = createBrowserPreviewPlatform();
  await Promise.all(characters.map((character) => platform.characters.save(character)));
  state.api = platform.characterRelation;
  state.platform = platform;
  state.listCharacters.mockReset().mockResolvedValue(characters);
});
afterEach(cleanup);

export function renderRelationSection(primary = "A"): ReturnType<typeof render> & { switchOwner(owner: string): void } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const element = (owner: string) => (
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <CharacterRelationSection primary={owner} />
      </I18nProvider>
    </QueryClientProvider>
  );
  const result = render(element(primary));
  return { ...result, switchOwner: (owner: string) => result.rerender(element(owner)) };
}
export async function seedRelationNode(owner: string, node: RelationNode) {
  return state.api!.applyRelationChanges(owner, [{ op: "add_node", node }]);
}

export { state };
