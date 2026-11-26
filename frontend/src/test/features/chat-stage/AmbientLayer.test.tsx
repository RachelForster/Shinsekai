import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AmbientLayer } from "../../../features/chat-stage/components/StageLayers";

describe("AmbientLayer", () => {
  const effects = [
    { key: "rain", layer: "back" as const, seq: 1, url: "rain.webm" },
    { key: "fog", layer: "front" as const, seq: 2, url: "fog.png" },
  ];

  it("renders only the effects assigned to its layer", () => {
    const { container } = render(<AmbientLayer effects={effects} hidden={false} layer="back" />);

    expect(container.querySelector(".ambient-layer")?.getAttribute("data-layer")).toBe("back");
    expect(container.querySelectorAll("video")).toHaveLength(1);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("renders images for non-video ambience", () => {
    const { container } = render(<AmbientLayer effects={effects} hidden={false} layer="front" />);

    expect(container.querySelectorAll("img")).toHaveLength(1);
    expect(container.querySelectorAll("video")).toHaveLength(0);
  });

  it("fades removed effects out before unmounting", () => {
    vi.useFakeTimers();
    try {
      const { container, rerender } = render(<AmbientLayer effects={effects} hidden={false} layer="front" />);
      expect(container.querySelectorAll("img")).toHaveLength(1);

      rerender(<AmbientLayer effects={[]} hidden={false} layer="front" />);
      expect(container.querySelector("img")?.getAttribute("data-state")).toBe("leaving");

      act(() => vi.advanceTimersByTime(500));
      expect(container.querySelector(".ambient-layer")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
