// @ts-expect-error -- Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from "node:fs";

import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import { BackgroundTransitionLayer } from "../../../features/chat-stage/components/BackgroundTransitionLayer";
import { SpriteMotionBox } from "../../../features/chat-stage/components/SpriteMotionBox";

const stageEffectsCss: string = readFileSync("src/features/chat-stage/styles/stage-effects.css", "utf8");

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

  it("restores unexpired backgroundTransition and spriteMotions from snapshot and drops expired ones", () => {
    const hydratedActive = chatStageReducer(emptyChatState, {
      type: "hydrate",
      snapshot: {
        ...emptyChatState,
        sessionId: "s1",
        eventSeq: 12,
        serverTimeMs: 1100,
        effectImage: null,
        backgroundPath: "/bg/night.png",
        backgroundTransition: {
          effect: "fade_black",
          durationMs: 680,
          expiresAt: 1680,
          seq: 11,
        },
        spriteMotions: {
          Alice: {
            motion: "shake",
            durationMs: 460,
            expiresAt: 1560,
            seq: 12,
          },
          OldExpired: {
            motion: "nod",
            durationMs: 460,
            expiresAt: 1050,
            seq: 8,
          },
        },
      },
    });
    expect(hydratedActive.backgroundTransition).toEqual({ effect: "fade_black", seq: 11 });
    expect(hydratedActive.spriteMotions).toEqual({
      Alice: { durationMs: 460, motion: "shake", seq: 12 },
    });

    // Repeated polling snapshot with same seq preserves existing entry object references.
    const repeatedPoll = chatStageReducer(hydratedActive, {
      type: "hydrate",
      snapshot: {
        ...emptyChatState,
        sessionId: "s1",
        eventSeq: 12,
        serverTimeMs: 1200,
        effectImage: null,
        backgroundPath: "/bg/night.png",
        backgroundTransition: {
          effect: "fade_black",
          durationMs: 680,
          expiresAt: 1680,
          seq: 11,
        },
        spriteMotions: {
          Alice: {
            motion: "shake",
            durationMs: 460,
            expiresAt: 1560,
            seq: 12,
          },
        },
      },
    });
    expect(repeatedPoll.backgroundTransition).toBe(hydratedActive.backgroundTransition);
    expect(repeatedPoll.spriteMotions.Alice).toBe(hydratedActive.spriteMotions.Alice);

    // Late reload after expiresAt drops expired transition and motion.
    const staleReload = chatStageReducer(emptyChatState, {
      type: "hydrate",
      snapshot: {
        ...emptyChatState,
        sessionId: "s1",
        eventSeq: 12,
        serverTimeMs: 2500,
        effectImage: null,
        backgroundPath: "/bg/night.png",
        backgroundTransition: {
          effect: "fade_black",
          durationMs: 680,
          expiresAt: 1680,
          seq: 11,
        },
        spriteMotions: {
          Alice: {
            motion: "shake",
            durationMs: 460,
            expiresAt: 1560,
            seq: 12,
          },
        },
      },
    });
    expect(staleReload.backgroundTransition).toBeNull();
    expect(staleReload.spriteMotions).toEqual({});
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

  it("anchors .sprite-motion-box transform-origin to character position CSS vars", () => {
    const blockMatch = stageEffectsCss.match(/\.sprite-motion-box\s*\{[\s\S]*?\}/);
    expect(blockMatch).not.toBeNull();
    const block = blockMatch![0];
    expect(block).toContain("--sprite-axis-center");
    expect(block).toContain("--sprite-offset-x");
    expect(block).not.toContain("transform-origin: center bottom");
  });
});
