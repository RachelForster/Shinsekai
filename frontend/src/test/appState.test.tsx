import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppStateProvider, useAppState } from "../shared/app-state/AppState";

function StateProbe() {
  const { dispatch, state } = useAppState();
  return (
    <div>
      <span data-testid="density">{state.density}</span>
      <span data-testid="language">{state.language}</span>
      <button onClick={() => dispatch({ density: "comfortable", type: "setDensity" })}>density</button>
      <button onClick={() => dispatch({ language: "en", type: "setLanguage" })}>language</button>
    </div>
  );
}

describe("AppStateProvider", () => {
  it("provides default app state and exposes density on the wrapper", () => {
    const { container } = render(
      <AppStateProvider>
        <StateProbe />
      </AppStateProvider>,
    );

    expect(screen.getByTestId("density")).toHaveTextContent("compact");
    expect(screen.getByTestId("language")).toHaveTextContent("zh_CN");
    expect(container.firstElementChild).toHaveAttribute("data-density", "compact");
  });

  it("updates density and language through dispatch", () => {
    const { container } = render(
      <AppStateProvider>
        <StateProbe />
      </AppStateProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "density" }));
    fireEvent.click(screen.getByRole("button", { name: "language" }));

    expect(screen.getByTestId("density")).toHaveTextContent("comfortable");
    expect(screen.getByTestId("language")).toHaveTextContent("en");
    expect(container.firstElementChild).toHaveAttribute("data-density", "comfortable");
  });
});
