import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import { BackgroundTransitionLayer } from "../../../features/chat-stage/components/BackgroundTransitionLayer";
import { SpriteMotionBox } from "../../../features/chat-stage/components/SpriteMotionBox";

describe("chat stage transitions & motions reducer", () => {
  it("tracks backgroundTransition and spriteMotions and resets them cleanly", () => {
    const withSprite = chatStageReducer(emptyChatState, {
      type: "event",
      event: {
        type: "sprite.show",
        characterName: "Alice",
        url: "/sprite.png",
        avatarType: "static",
        modelUrl: "",
        scale: 1,
        seq: 1,
        ts: 1,
        v: 1,
      },
    });

    const withMotion = chatStageReducer(withSprite, {
      type: "event",
      event: {
        type: "sprite.motion",
        characterName: "Alice",
        motion: "shake",
        durationMs: 460,
        seq: 2,
        ts: 2,
        v: 1,
      },
    });
    expect(withMotion.spriteMotions.Alice).toEqual({
      motion: "shake",
      durationMs: 460,
      seq: 2,
    });

    const sameScene = chatStageReducer(withMotion, {
      type: "event",
      event: {
        type: "background.change",
        url: "",
        transition: "fade_black",
        seq: 3,
        ts: 3,
        v: 1,
      },
    });
    expect(sameScene.backgroundTransition).toEqual({ effect: "fade_black", seq: 3 });
    expect(sameScene.spriteMotions.Alice).toBeDefined();

    const newScene = chatStageReducer(sameScene, {
      type: "event",
      event: {
        type: "background.change",
        url: "/bg/night.png",
        transition: "slide_left",
        seq: 4,
        ts: 4,
        v: 1,
      },
    });
    expect(newScene.backgroundTransition).toEqual({ effect: "slide_left", seq: 4 });
    expect(newScene.spriteMotions).toEqual({});

    const withBobMotion = chatStageReducer(newScene, {
      type: "event",
      event: {
        type: "sprite.motion",
        characterName: "Bob",
        motion: "jump",
        durationMs: 480,
        seq: 5,
        ts: 5,
        v: 1,
      },
    });
    const afterRemove = chatStageReducer(withBobMotion, {
      type: "event",
      event: {
        type: "sprite.remove",
        characterName: "Bob",
        seq: 6,
        ts: 6,
        v: 1,
      },
    });
    expect(afterRemove.spriteMotions.Bob).toBeUndefined();

    const afterHydrate = chatStageReducer(withBobMotion, {
      type: "hydrate",
      snapshot: { ...emptyChatState, effectImage: null, sessionId: "s1", eventSeq: 10 },
    });
    expect(afterHydrate.backgroundTransition).toBeNull();
    expect(afterHydrate.spriteMotions).toEqual({});
  });
});

describe("BackgroundTransitionLayer & SpriteMotionBox", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("animates outgoing, incoming, and curtain layers and cleans up after duration", () => {
    vi.useFakeTimers();
    const { container, rerender } = render(
      <BackgroundTransitionLayer hidden={false} path="/bg/day.png" transparent={false} />,
    );
    expect(container.querySelectorAll(".stage-bg-layer")).toHaveLength(1);

    rerender(
      <BackgroundTransitionLayer
        hidden={false}
        path="/bg/night.png"
        transition={{ effect: "fade_black", seq: 2 }}
        transparent={false}
      />,
    );
    expect(container.querySelector(".stage-bg-layer--outgoing")).not.toBeNull();
    expect(container.querySelector(".stage-bg-layer--incoming")).not.toBeNull();
    expect(container.querySelector('.stage-bg-curtain[data-transition="fade_black"]')).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(900);
    });
    expect(container.querySelector(".stage-bg-layer--outgoing")).toBeNull();
    expect(container.querySelector(".stage-bg-curtain")).toBeNull();
  });

  it("applies sprite motion without remounting child avatar subtree", () => {
    vi.useFakeTimers();
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => window.setTimeout(() => cb(0), 0));
    vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));

    let mounts = 0;
    function ChildAvatar() {
      mounts += 1;
      return <span data-testid="avatar">avatar</span>;
    }

    const { container, rerender } = render(
      <SpriteMotionBox motion={null}>
        <ChildAvatar />
      </SpriteMotionBox>,
    );
    expect(screen.getByTestId("avatar")).toBeInTheDocument();
    const initialMounts = mounts;

    rerender(
      <SpriteMotionBox motion={{ motion: "shake", durationMs: 460, seq: 1 }}>
        <ChildAvatar />
      </SpriteMotionBox>,
    );
    act(() => {
      vi.advanceTimersByTime(16);
    });
    const box = container.querySelector(".sprite-motion-box");
    expect(box).toHaveAttribute("data-motion", "shake");
    expect(mounts).toBe(initialMounts + 1);

    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(box).not.toHaveAttribute("data-motion");
  });
});
