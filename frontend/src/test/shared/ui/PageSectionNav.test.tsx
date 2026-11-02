import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PageSectionNav } from "../../../shared/ui";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PageSectionNav", () => {
  it("scrolls the nearest content outlet under the sticky page header", () => {
    const scrollTo = vi.fn();
    render(
      <div className="content-outlet">
        <div className="page">
          <header className="page__header">Header</header>
          <PageSectionNav ariaLabel="Sections" items={[{ id: "api", label: "API" }]} />
          <section id="api">API section</section>
        </div>
      </div>,
    );

    const container = document.querySelector(".content-outlet") as HTMLElement;
    const header = document.querySelector(".page__header") as HTMLElement;
    const target = document.getElementById("api") as HTMLElement;
    Object.defineProperty(container, "scrollTop", { configurable: true, value: 25, writable: true });
    Object.defineProperty(container, "scrollTo", { configurable: true, value: scrollTo });
    vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
      bottom: 400,
      height: 400,
      left: 0,
      right: 300,
      top: 50,
      width: 300,
      x: 0,
      y: 50,
      toJSON: () => ({}),
    });
    vi.spyOn(header, "getBoundingClientRect").mockReturnValue({
      bottom: 110,
      height: 60,
      left: 0,
      right: 300,
      top: 50,
      width: 300,
      x: 0,
      y: 50,
      toJSON: () => ({}),
    });
    vi.spyOn(target, "getBoundingClientRect").mockReturnValue({
      bottom: 350,
      height: 100,
      left: 0,
      right: 300,
      top: 250,
      width: 300,
      x: 0,
      y: 250,
      toJSON: () => ({}),
    });

    fireEvent.click(screen.getByRole("button", { name: "API" }));

    expect(scrollTo).toHaveBeenCalledWith({
      behavior: "smooth",
      top: 153,
    });
  });

  it("falls back to window scrolling and ignores missing targets", () => {
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    Object.defineProperty(window, "scrollY", { configurable: true, value: 10 });
    render(
      <>
        <PageSectionNav
          ariaLabel="Loose sections"
          items={[
            { id: "loose", label: "Loose" },
            { id: "missing", label: "Missing" },
          ]}
        />
        <section id="loose">Loose section</section>
      </>,
    );
    const target = document.getElementById("loose") as HTMLElement;
    vi.spyOn(target, "getBoundingClientRect").mockReturnValue({
      bottom: 300,
      height: 100,
      left: 0,
      right: 300,
      top: 200,
      width: 300,
      x: 0,
      y: 200,
      toJSON: () => ({}),
    });

    fireEvent.click(screen.getByRole("button", { name: "Loose" }));
    fireEvent.click(screen.getByRole("button", { name: "Missing" }));

    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith({ behavior: "smooth", top: 198 });
  });
});
