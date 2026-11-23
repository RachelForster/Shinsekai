import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import {
  PageSectionHost,
  PageSectionNav,
  useVisibleSectionNavItems,
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
});
