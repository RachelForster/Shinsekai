import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useReminderAudio } from "../../../features/reminders/useReminderAudio";
import type { ReminderNotice } from "../../../entities/reminder/types";

const mocks = vi.hoisted(() => ({ visible: vi.fn(), hidden: vi.fn(), snapshot: vi.fn(), subscribe: vi.fn() }));
vi.mock("../../../entities/chat/repository", () => ({
  getChatSnapshot: mocks.snapshot,
  subscribeChat: mocks.subscribe,
}));
vi.mock("../../../shared/desktop/remindersApi", () => ({
  isReminderWindowVisible: mocks.visible,
  onReminderWindowHidden: mocks.hidden,
}));
vi.mock("../../../entities/files/repository", () => ({ fileUrl: (path: string) => `/media/${path}` }));

class FakeAudio {
  static instances: FakeAudio[] = [];
  volume = 1;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn();
  constructor(public src: string) {
    FakeAudio.instances.push(this);
  }
}

const notice: ReminderNotice = {
  id: "one",
  character_name: "澪",
  title: "睡觉",
  message: "该睡啦",
  due_at: "2026-09-12T23:00:00",
};
const voiced = { ...notice, audio_path: "first.wav", audio_volume: 0.7 };

describe("reminder voice playback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    FakeAudio.instances = [];
    vi.stubGlobal("Audio", FakeAudio);
    mocks.visible.mockResolvedValue(true);
    mocks.hidden.mockResolvedValue(vi.fn());
    mocks.snapshot.mockResolvedValue({ characterSpeechDisabled: false });
    mocks.subscribe.mockReturnValue(vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("plays newly generated audio once, using its media URL and character volume", async () => {
    const hook = renderHook(({ notices }) => useReminderAudio(notices), { initialProps: { notices: [notice] } });
    expect(FakeAudio.instances).toHaveLength(0);
    hook.rerender({ notices: [voiced] });
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    expect(mocks.snapshot).toHaveBeenCalledWith({ claimRenderer: false });
    expect(mocks.subscribe).toHaveBeenCalledWith(expect.any(Function), { claimRenderer: false });
    const player = FakeAudio.instances[0];
    expect(player.src).toBe("/media/first.wav");
    expect(player.volume).toBe(0.7);
    await act(async () => player.onended?.());
    hook.rerender({ notices: [{ ...voiced }] });
    expect(FakeAudio.instances).toHaveLength(1);
    hook.unmount();
    renderHook(() => useReminderAudio([voiced]));
    expect(FakeAudio.instances).toHaveLength(1);
  });

  it("serializes multiple arrivals, but plays a later recurrence of the same schedule", async () => {
    const later = { ...voiced, due_at: "2026-09-13T23:00:00", audio_path: "second.wav" };
    renderHook(() => useReminderAudio([later, voiced]));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    expect(FakeAudio.instances[0].src).toBe("/media/first.wav");
    await act(async () => FakeAudio.instances[0].onended?.());
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(2));
    expect(FakeAudio.instances[1].src).toBe("/media/second.wav");
  });

  it("stops immediately on native hide and supports explicit replay", async () => {
    const hook = renderHook(() => useReminderAudio([voiced]));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    await act(async () => mocks.hidden.mock.calls[0][0]());
    expect(FakeAudio.instances[0].pause).toHaveBeenCalledOnce();
    expect(hook.result.current.playing).toBe("");
    await act(async () => hook.result.current.replay(voiced));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(2));
  });

  it("persists mute, stops the current voice, and does not play skipped reminders on unmute", async () => {
    const hook = renderHook(({ notices }) => useReminderAudio(notices), { initialProps: { notices: [voiced] } });
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    await act(async () => hook.result.current.toggleMute());
    expect(FakeAudio.instances[0].pause).toHaveBeenCalledOnce();
    expect(localStorage.getItem("shinsekai.reminder.muted")).toBe("true");
    hook.rerender({ notices: [{ ...voiced, id: "two" }, voiced] });
    await act(async () => hook.result.current.toggleMute());
    expect(FakeAudio.instances).toHaveLength(1);
    await act(async () => hook.result.current.replay(voiced));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(2));
  });

  it("does not play when synthesis completes after the popup is hidden", async () => {
    mocks.visible.mockResolvedValue(false);
    renderHook(() => useReminderAudio([voiced]));
    await waitFor(() => expect(mocks.visible).toHaveBeenCalled());
    expect(FakeAudio.instances).toHaveLength(0);
  });

  it("cancels a pending visibility check when stopped", async () => {
    let resolve: (visible: boolean) => void = () => {};
    mocks.visible.mockReturnValue(
      new Promise<boolean>((done) => {
        resolve = done;
      }),
    );
    const hook = renderHook(() => useReminderAudio([voiced]));
    act(() => hook.result.current.stop());
    await act(async () => resolve(true));
    expect(FakeAudio.instances).toHaveLength(0);
  });

  it("suppresses cached audio and replay during continuous ASR, preserving the saved mute setting", async () => {
    mocks.snapshot.mockResolvedValue({ characterSpeechDisabled: true });
    const hook = renderHook(() => useReminderAudio([voiced]));
    await waitFor(() => expect(hook.result.current.speechDisabled).toBe(true));
    await act(async () => {
      hook.result.current.toggleMute();
      hook.result.current.replay(voiced);
    });
    expect(FakeAudio.instances).toHaveLength(0);
    expect(localStorage.getItem("shinsekai.reminder.muted")).toBeNull();
    mocks.snapshot.mockResolvedValue({ characterSpeechDisabled: false });
    act(() => mocks.subscribe.mock.calls[0][0]({ characterSpeechDisabled: false }));
    await act(async () => hook.result.current.replay(voiced));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
  });

  it("stops playing audio when the runtime enters continuous ASR and clears queued speech", async () => {
    const hook = renderHook(() => useReminderAudio([{ ...voiced, id: "two" }, voiced]));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    await act(async () => mocks.subscribe.mock.calls[0][0]({ characterSpeechDisabled: true }));
    expect(FakeAudio.instances[0].pause).toHaveBeenCalledOnce();
    expect(hook.result.current.playing).toBe("");
    expect(hook.result.current.muted).toBe(true);
    expect(FakeAudio.instances).toHaveLength(1);
    expect(localStorage.getItem("shinsekai.reminder.muted")).toBeNull();
  });

  it("revokes an in-flight playback policy check when the experiment becomes active", async () => {
    let resolve: (snapshot: { characterSpeechDisabled: boolean }) => void = () => {};
    mocks.snapshot.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    renderHook(() => useReminderAudio([voiced]));
    await act(async () => mocks.subscribe.mock.calls[0][0]({ characterSpeechDisabled: true }));
    await act(async () => resolve({ characterSpeechDisabled: false }));
    expect(FakeAudio.instances).toHaveLength(0);
  });

  it("does not play when initial session policy is unknown and snapshot fetch fails, but keeps retry available", async () => {
    mocks.snapshot.mockRejectedValue(new Error("network error"));
    const hook = renderHook(() => useReminderAudio([voiced]));
    await waitFor(() => expect(mocks.snapshot).toHaveBeenCalled());
    expect(FakeAudio.instances).toHaveLength(0);
    expect(hook.result.current.speechDisabled).toBe(false);
    expect(hook.result.current.muted).toBe(false);

    mocks.snapshot.mockResolvedValue({ characterSpeechDisabled: false });
    await act(async () => hook.result.current.replay(voiced));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    expect(FakeAudio.instances[0].src).toBe("/media/first.wav");
  });

  it("preserves last known OFF policy on snapshot error and plays cached reminders normally", async () => {
    const hook = renderHook(({ notices }) => useReminderAudio(notices), { initialProps: { notices: [voiced] } });
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    await act(async () => FakeAudio.instances[0].onended?.());

    mocks.snapshot.mockRejectedValue(new Error("snapshot fetch failed"));
    const secondNotice = { ...voiced, due_at: "2026-09-13T23:00:00", audio_path: "second.wav" };
    hook.rerender({ notices: [secondNotice, voiced] });
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(2));
    expect(FakeAudio.instances[1].src).toBe("/media/second.wav");
    expect(hook.result.current.speechDisabled).toBe(false);
  });

  it("preserves last known ON policy on snapshot error and keeps speech suppressed", async () => {
    mocks.snapshot.mockResolvedValueOnce({ characterSpeechDisabled: true });
    const hook = renderHook(({ notices }) => useReminderAudio(notices), { initialProps: { notices: [voiced] } });
    await waitFor(() => expect(hook.result.current.speechDisabled).toBe(true));
    expect(FakeAudio.instances).toHaveLength(0);

    mocks.snapshot.mockRejectedValue(new Error("network broken"));
    const secondNotice = { ...voiced, due_at: "2026-09-13T23:00:00", audio_path: "second.wav" };
    hook.rerender({ notices: [secondNotice, voiced] });
    await act(async () => hook.result.current.replay(secondNotice));
    expect(FakeAudio.instances).toHaveLength(0);
    expect(hook.result.current.speechDisabled).toBe(true);
  });

  it("guards against a stale snapshot response overriding a newer subscribeChat OFF transition", async () => {
    let resolveSnapshot: (val: { characterSpeechDisabled: boolean }) => void = () => {};
    mocks.snapshot.mockReturnValue(
      new Promise((resolve) => {
        resolveSnapshot = resolve;
      }),
    );
    const hook = renderHook(() => useReminderAudio([voiced]));
    await act(async () => mocks.subscribe.mock.calls[0][0]({ characterSpeechDisabled: false }));
    expect(hook.result.current.speechDisabled).toBe(false);

    await act(async () => resolveSnapshot({ characterSpeechDisabled: true }));
    expect(hook.result.current.speechDisabled).toBe(false);
    await act(async () => hook.result.current.replay(voiced));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
  });

  it("stops playing immediately when subscribeChat event transitions policy to ON", async () => {
    const hook = renderHook(() => useReminderAudio([voiced]));
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    expect(hook.result.current.playing).toBe("one:2026-09-12T23:00:00");

    await act(async () => mocks.subscribe.mock.calls[0][0]({ characterSpeechDisabled: true }));
    expect(FakeAudio.instances[0].pause).toHaveBeenCalledOnce();
    expect(hook.result.current.playing).toBe("");
    expect(hook.result.current.speechDisabled).toBe(true);
  });
});
