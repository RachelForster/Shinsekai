import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDialogTypewriter } from "../../../features/chat-stage/hooks/useDialogTypewriter";
import type { ChatRuntimeStatus } from "../../../shared/platform/types";

describe("useDialogTypewriter", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not auto-advance while the current voice is still playing", () => {
    vi.useFakeTimers();
    const onAutoAdvance = vi.fn();
    const makeProps = (status: ChatRuntimeStatus) => ({
      auto: true,
      characterName: "Mio",
      dialogVisible: true,
      html: "<p>Current line</p>",
      onAutoAdvance,
      optionsVisible: false,
      status,
      text: "Current line",
      textDirection: "ltr" as const,
      typewriterCps: 30,
    });
    const { rerender } = renderHook(
      ({ status }: { status: ChatRuntimeStatus }) => useDialogTypewriter(makeProps(status)),
      {
        initialProps: { status: "speaking" as ChatRuntimeStatus },
      },
    );

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(onAutoAdvance).not.toHaveBeenCalled();

    rerender({ status: "idle" });
    act(() => {
      vi.advanceTimersByTime(1_599);
    });
    expect(onAutoAdvance).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onAutoAdvance).toHaveBeenCalledOnce();
  });
});
