import { it, expect, vi } from "vitest";
import { bindAvatarVoice, routeAvatarVoice } from "../../../modules/character-visual/voiceRoute";
import type { AvatarSession } from "../../../modules/character-visual/contracts";

it("routes by the queued voice's character and only actual mouth capability", () => {
  const a = { capabilities: { mouth: true }, setMouthOpen: vi.fn() } as unknown as AvatarSession<unknown, unknown>;
  const b = { capabilities: { mouth: false }, setMouthOpen: vi.fn() } as unknown as AvatarSession<unknown, unknown>;
  const unbindA = bindAvatarVoice("A", a);
  const unbindB = bindAvatarVoice("B", b);
  routeAvatarVoice("B", 1);
  expect(a.setMouthOpen).not.toHaveBeenCalled();
  expect(b.setMouthOpen).not.toHaveBeenCalled();
  routeAvatarVoice("A", 0.6);
  expect(a.setMouthOpen).toHaveBeenLastCalledWith(0.6);
  unbindA();
  expect(a.setMouthOpen).toHaveBeenLastCalledWith(0);
  routeAvatarVoice("A", 1);
  expect(a.setMouthOpen).toHaveBeenLastCalledWith(0);
  unbindB();
});
