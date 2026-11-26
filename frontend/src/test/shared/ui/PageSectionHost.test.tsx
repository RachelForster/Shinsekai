import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import {
  PageSectionHost,
  PageSectionNav,
  useSectionBusyRegistry,
  useVisibleSectionNavItems,
  withSectionBusy,
  type PageSectionDescriptor,
  type PageSectionProps,
} from "../../../shared/ui";

interface TestCtx {
  labelPrefix: string;
  showHidden: boolean;
}

type TestSlot = "body" | "sidebar";

function makeSection(name: string) {
  return function TestSection({ ctx, id }: PageSectionProps<TestCtx>) {
    return (
      <section data-testid="rendered-section" id={id}>
        {ctx.labelPrefix}:{name}:{id}
      </section>
    );
  };
}

const TEST_SECTIONS: readonly PageSectionDescriptor<TestCtx, TestSlot>[] = [
  {
    Component: makeSection("third"),
    id: "sec-third",
    navLabelKey: "effect.section.audio",
    order: 30,
  },
  {
    Component: makeSection("hidden"),
    id: "sec-hidden",
    isVisible: (ctx) => ctx.showHidden,
    navLabelKey: "effect.section.ambient",
    order: 15,
  },
  {
    Component: makeSection("first"),
    id: "sec-first",
    navLabelKey: "effect.section.info",
    order: 10,
  },
  {
    Component: makeSection("unlisted"),
    id: "sec-unlisted",
    order: 20,
  },
  {
    Component: makeSection("sidebar"),
    id: "sec-sidebar",
    navLabelKey: "effect.section.image",
    order: 5,
    slot: "sidebar",
  },
];

function Harness({ ctx, slot }: { ctx: TestCtx; slot?: TestSlot }) {
  const navItems = useVisibleSectionNavItems(TEST_SECTIONS, ctx);
  return (
    <div>
      <PageSectionNav ariaLabel="Test nav" items={navItems} />
      <main data-testid="host-container">
        <PageSectionHost ctx={ctx} sections={TEST_SECTIONS} slot={slot} />
      </main>
    </div>
  );
}

function renderHarness(ctx: TestCtx, slot?: TestSlot) {
  return render(
    <I18nProvider language="en">
      <Harness ctx={ctx} slot={slot} />
    </I18nProvider>,
  );
}

describe("PageSectionHost", () => {
  it("renders visible sections in ascending order with explicit ctx and id props and derives matching nav items", () => {
    renderHarness({ labelPrefix: "alpha", showHidden: false });

    const rendered = screen.getAllByTestId("rendered-section");
    expect(rendered.map((node) => node.textContent)).toEqual([
      "alpha:sidebar:sec-sidebar",
      "alpha:first:sec-first",
      "alpha:unlisted:sec-unlisted",
      "alpha:third:sec-third",
    ]);

    const navButtons = screen.getAllByRole("button");
    expect(navButtons.map((button) => button.textContent)).toEqual(["Image effects", "Basic info", "Effect audio"]);
  });

  it("includes conditional sections in both host output and nav items when isVisible becomes true", () => {
    renderHarness({ labelPrefix: "beta", showHidden: true });

    const rendered = screen.getAllByTestId("rendered-section");
    expect(rendered.map((node) => node.id)).toEqual([
      "sec-sidebar",
      "sec-first",
      "sec-hidden",
      "sec-unlisted",
      "sec-third",
    ]);

    const navButtons = screen.getAllByRole("button");
    expect(navButtons.map((button) => button.textContent)).toEqual([
      "Image effects",
      "Basic info",
      "Full-screen ambience",
      "Effect audio",
    ]);
  });

  it("filters sections by slot when slot is provided", () => {
    renderHarness({ labelPrefix: "gamma", showHidden: false }, "body");

    const rendered = screen.getAllByTestId("rendered-section");
    expect(rendered.map((node) => node.id)).toEqual(["sec-first", "sec-unlisted", "sec-third"]);
  });

  it("tracks synchronous ref-counted busy leases, independent flags, and resumeRevision", async () => {
    const events: string[] = [];
    let resolveBeforeBusy: (() => void) | null = null;
    const onBeforeBusy = vi.fn(() => {
      events.push("beforeBusy");
      return new Promise<void>((resolve) => {
        resolveBeforeBusy = resolve;
      });
    });

    const { result } = renderHook(() => useSectionBusyRegistry({ onBeforeBusy }));
    expect(result.current.busyCount).toBe(0);
    expect(result.current.resumeRevision).toBe(0);

    let leaseA!: ReturnType<typeof result.current.beginSectionBusy>;
    let leaseB!: ReturnType<typeof result.current.beginSectionBusy>;
    let settledDone = false;

    act(() => {
      leaseA = result.current.beginSectionBusy("sec-a");
      void leaseA.settled.then(() => {
        settledDone = true;
      });
      events.push("afterBegin");
    });

    expect(events).toEqual(["beforeBusy", "afterBegin"]);
    expect(result.current.busyCount).toBe(1);
    expect(settledDone).toBe(false);

    await act(async () => {
      resolveBeforeBusy?.();
      await leaseA.settled;
    });
    expect(settledDone).toBe(true);

    act(() => {
      leaseB = result.current.beginSectionBusy("sec-b");
      result.current.setSectionBusy("modal-a", true);
      result.current.setSectionBusy("modal-a", true);
    });
    expect(result.current.busyCount).toBe(3);

    act(() => {
      leaseA.release();
      leaseA.release();
    });
    expect(result.current.busyCount).toBe(2);
    expect(result.current.resumeRevision).toBe(0);

    act(() => {
      result.current.setSectionBusy("modal-a", false);
    });
    expect(result.current.busyCount).toBe(1);
    expect(result.current.resumeRevision).toBe(0);

    act(() => {
      leaseB.release();
    });
    expect(result.current.busyCount).toBe(0);
    expect(result.current.resumeRevision).toBe(1);

    const rejectingHook = renderHook(() =>
      useSectionBusyRegistry({
        onBeforeBusy: () => Promise.reject(new Error("drain failed")),
      }),
    );
    let rejectingLease!: ReturnType<typeof rejectingHook.result.current.beginSectionBusy>;
    await act(async () => {
      rejectingLease = rejectingHook.result.current.beginSectionBusy("sec-reject");
      await expect(rejectingLease.settled).resolves.toBeUndefined();
      rejectingLease.release();
    });
    expect(rejectingHook.result.current.busyCount).toBe(0);
  });

  it("wires withSectionBusy into zero-arg and param mutations, waits for settled, and chains onSettled", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const events: string[] = [];
    let resolveBeforeBusy: (() => void) | null = null;
    let resolveZeroArg: (() => void) | null = null;
    let rejectParam: ((err: Error) => void) | null = null;

    const zeroArgFn = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          events.push("zeroArgFn");
          resolveZeroArg = () => resolve("ok");
        }),
    );
    const paramFn = vi.fn(
      (_id: string) =>
        new Promise<string>((_resolve, reject) => {
          events.push("paramFn");
          rejectParam = reject;
        }),
    );
    const customOnSettled = vi.fn((_data, error, variables) => {
      events.push(`customOnSettled:${variables}:${error instanceof Error ? error.message : "none"}`);
    });

    const { result } = renderHook(
      () => {
        const registry = useSectionBusyRegistry({
          onBeforeBusy: () => {
            events.push("beforeBusy");
            return new Promise<void>((resolve) => {
              resolveBeforeBusy = resolve;
            });
          },
        });
        const zeroMutation = useMutation(
          withSectionBusy(registry.beginSectionBusy, "sec-zero", {
            mutationFn: () => zeroArgFn(),
          }),
        );
        const paramMutation = useMutation(
          withSectionBusy(registry.beginSectionBusy, "sec-param", {
            mutationFn: (id: string) => paramFn(id),
            onSettled: customOnSettled,
          }),
        );
        return { paramMutation, registry, zeroMutation };
      },
      { wrapper },
    );

    act(() => {
      result.current.zeroMutation.mutate();
      events.push("afterMutateCall");
    });

    expect(events).toEqual(["beforeBusy", "afterMutateCall"]);
    expect(zeroArgFn).not.toHaveBeenCalled();
    expect(result.current.registry.busyCount).toBe(1);

    await act(async () => {
      resolveBeforeBusy?.();
      await Promise.resolve();
    });
    expect(zeroArgFn).toHaveBeenCalledTimes(1);
    expect(result.current.registry.busyCount).toBe(1);

    await act(async () => {
      resolveZeroArg?.();
      await Promise.resolve();
    });
    expect(result.current.registry.busyCount).toBe(0);
    expect(result.current.registry.resumeRevision).toBe(1);

    await act(async () => {
      result.current.paramMutation.mutate("item-1");
      await Promise.resolve();
    });
    expect(paramFn).not.toHaveBeenCalled();
    expect(result.current.registry.busyCount).toBe(1);

    await act(async () => {
      resolveBeforeBusy?.();
      await Promise.resolve();
    });
    expect(paramFn).toHaveBeenCalledWith("item-1");

    await act(async () => {
      rejectParam?.(new Error("boom"));
      await Promise.resolve();
    });
    expect(result.current.registry.busyCount).toBe(0);
    expect(result.current.registry.resumeRevision).toBe(2);
    expect(events).toContain("customOnSettled:item-1:boom");
  });
});
