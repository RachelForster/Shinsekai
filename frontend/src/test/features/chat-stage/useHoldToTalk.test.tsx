import { act, fireEvent, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useHoldToTalk } from "../../../features/chat-stage/hooks/useHoldToTalk";

describe("hold to talk", () => {
  it("orders a quick release after start and ignores key repetition", async () => {
    let started!: () => void;
    const onCommand = vi.fn().mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          started = resolve;
        }),
    );
    renderHook(() => useHoldToTalk({ enabled: true, disabled: false, onCommand }));
    fireEvent.keyDown(window, { code: "F8" });
    fireEvent.keyDown(window, { code: "F8", repeat: true });
    fireEvent.keyUp(window, { code: "F8" });
    await waitFor(() => expect(onCommand).toHaveBeenCalledTimes(1));
    expect(onCommand).toHaveBeenNthCalledWith(1, { type: "begin-asr-hold" });
    await act(async () => started());
    await waitFor(() => expect(onCommand).toHaveBeenCalledTimes(2));
    expect(onCommand).toHaveBeenNthCalledWith(2, { type: "finish-asr-hold" });
    fireEvent.keyUp(window, { code: "F8" });
    expect(onCommand).toHaveBeenCalledTimes(2);
  });

  it.each(["escape", "blur", "disabled", "off", "unmount"])("cancels on %s without sending", async (reason) => {
    const onCommand = vi.fn().mockResolvedValue(undefined);
    const { rerender, unmount } = renderHook((props) => useHoldToTalk({ ...props, onCommand }), {
      initialProps: { enabled: true, disabled: false },
    });
    fireEvent.keyDown(window, { code: "F8" });
    await waitFor(() => expect(onCommand).toHaveBeenCalledWith({ type: "begin-asr-hold" }));
    if (reason === "escape") fireEvent.keyDown(window, { key: "Escape" });
    if (reason === "blur") fireEvent.blur(window);
    if (reason === "disabled") rerender({ enabled: true, disabled: true });
    if (reason === "off") rerender({ enabled: false, disabled: false });
    if (reason === "unmount") unmount();
    fireEvent.keyUp(window, { code: "F8" });
    await waitFor(() => expect(onCommand).toHaveBeenCalledTimes(2));
    expect(onCommand).toHaveBeenLastCalledWith({ type: "cancel-asr-hold" });
  });

  it("does not start while off, blocked, composing, or using a modified shortcut", async () => {
    const onCommand = vi.fn();
    const { rerender } = renderHook((props) => useHoldToTalk({ ...props, onCommand }), {
      initialProps: { enabled: false, disabled: false },
    });
    fireEvent.keyDown(window, { code: "F8" });
    rerender({ enabled: true, disabled: true });
    fireEvent.keyDown(window, { code: "F8" });
    rerender({ enabled: true, disabled: false });
    fireEvent.keyDown(window, { code: "F8", ctrlKey: true });
    fireEvent.keyDown(window, { code: "F8", isComposing: true });
    fireEvent.keyDown(window, { code: "Space" });
    await act(async () => {});
    expect(onCommand).not.toHaveBeenCalled();
  });
});
