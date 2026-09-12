import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EffectImageLayer } from "../../../features/chat-stage/components/StageLayers";

describe("EffectImageLayer", () => {
  afterEach(() => vi.useRealTimers());

  it("uses the remaining monotonic lifetime for visibility and resumes the animation", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date", "performance"] });
    const effect = { deadline: performance.now() + 600, durationMs: 1000, seq: 1, label: "key", url: "key.png" };
    render(<EffectImageLayer effect={effect} />);
    expect(screen.getByRole("status")).toHaveStyle({ animationDuration: "1000ms", animationDelay: "-400ms" });
    act(() => vi.setSystemTime(new Date("2040-01-01")));
    act(() => vi.advanceTimersByTime(599));
    expect(screen.getByAltText("key")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByAltText("key")).not.toBeInTheDocument();
  });

  it("replaces the previous image timer when a new effect arrives", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
    const effect = { deadline: performance.now() + 1000, durationMs: 1000, seq: 1, label: "key", url: "key.png" };
    const { rerender } = render(<EffectImageLayer effect={effect} />);
    act(() => vi.advanceTimersByTime(500));
    rerender(<EffectImageLayer effect={{ ...effect, deadline: performance.now() + 2000, durationMs: 2000, seq: 2 }} />);
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByAltText("key")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1500));
    expect(screen.queryByAltText("key")).not.toBeInTheDocument();
  });
});
