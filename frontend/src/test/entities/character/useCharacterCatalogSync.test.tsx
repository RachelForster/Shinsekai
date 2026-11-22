import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { charactersQueryKey, listCharacters } from "../../../entities/character/repository";
import { useCharacterCatalogSync } from "../../../entities/character/useCharacterCatalogSync";
import { sampleConfig } from "../../../shared/platform/sampleData";

const mocks = vi.hoisted(() => ({ getPlatform: vi.fn() }));
vi.mock("../../../shared/platform/platform", () => ({ getPlatform: mocks.getPlatform }));

function Sync() {
  useCharacterCatalogSync();
  return null;
}

function Catalog() {
  const { data = [] } = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters });
  return <div data-testid="catalog">{JSON.stringify(data)}</div>;
}

describe("character catalog synchronization", () => {
  beforeEach(() => vi.clearAllMocks());

  it("applies host saves and sprite imports with no Agent panel mounted, without reloading unchanged catalogs", async () => {
    let revision = "first";
    let characters = structuredClone(sampleConfig.characters);
    const list = vi.fn(async () => structuredClone(characters));
    const getRevision = vi.fn(async () => revision);
    mocks.getPlatform.mockReturnValue({ characters: { list, revision: getRevision } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(charactersQueryKey, characters);
    render(
      <QueryClientProvider client={client}>
        <Sync />
        <Catalog />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(list).toHaveBeenCalledOnce());
    await act(() => client.refetchQueries({ queryKey: ["character-catalog-revision"] }));
    expect(list).toHaveBeenCalledOnce();

    characters = [{ ...characters[0], character_setting: "Updated by Agent", sprites: [] }];
    revision = "saved";
    // The next version poll refreshes an actively cached list on the same page.
    await waitFor(() => expect(screen.getByTestId("catalog")).toHaveTextContent("Updated by Agent"), {
      timeout: 2500,
    });
    expect(list).toHaveBeenCalledTimes(2);

    characters = [
      {
        ...characters[0],
        sprites: Array.from({ length: 10 }, (_, index) => ({
          path: `generated-${index}.png`,
          voice_type: "reference" as const,
        })),
      },
    ];
    revision = "imported";
    await waitFor(() => expect(screen.getByTestId("catalog")).toHaveTextContent("generated-9.png"), {
      timeout: 2500,
    });
    expect(list).toHaveBeenCalledTimes(3);
    client.clear();
  });

  it("invalidates an inactive cached list when the first version arrives after a host change", async () => {
    const list = vi.fn(async () => [{ ...sampleConfig.characters[0], name: "Created in host" }]);
    mocks.getPlatform.mockReturnValue({ characters: { list, revision: async () => "latest" } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(charactersQueryKey, []);
    const wrap = (catalog: boolean) => (
      <QueryClientProvider client={client}>
        <Sync />
        {catalog && <Catalog />}
      </QueryClientProvider>
    );
    const view = render(wrap(false));
    await waitFor(() => expect(client.getQueryState(charactersQueryKey)?.isInvalidated).toBe(true));
    expect(list).not.toHaveBeenCalled();
    view.rerender(wrap(true));
    await waitFor(() => expect(screen.getByTestId("catalog")).toHaveTextContent("Created in host"));
    client.clear();
  });
});
