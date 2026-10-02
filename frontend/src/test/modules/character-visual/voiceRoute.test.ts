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

it("starts routing when a loaded model's saved state selects a mouth morph", () => {
  const capability = { mouth: false };
  const session = { capabilities: capability, setMouthOpen: vi.fn() } as unknown as AvatarSession<unknown, unknown>;
  const unbind = bindAvatarVoice("custom-pmx", session);
  routeAvatarVoice("custom-pmx", 0.5);
  expect(session.setMouthOpen).not.toHaveBeenCalled();
  capability.mouth = true;
  routeAvatarVoice("custom-pmx", 0.8);
  expect(session.setMouthOpen).toHaveBeenLastCalledWith(0.8);
  unbind();
});

it("routes speech overlays without mouth bindings and stops every bound instance on unbind", () => {
  const sessions = [false, true].map((mouth) => ({
    capabilities: { mouth },
    setMouthOpen: vi.fn(),
    setSpeechLevel: vi.fn(),
  }));
  const unbind = sessions.map((session) =>
    bindAvatarVoice("head-only", session as unknown as AvatarSession<unknown, unknown>),
  );
  routeAvatarVoice("another-character", 1);
  expect(sessions[0].setSpeechLevel).not.toHaveBeenCalled();
  routeAvatarVoice("head-only", 0.8);
  for (const session of sessions) expect(session.setSpeechLevel).toHaveBeenLastCalledWith(0.8);
  expect(sessions[0].setMouthOpen).not.toHaveBeenCalled();
  expect(sessions[1].setMouthOpen).toHaveBeenLastCalledWith(0.8);
  unbind.forEach((cleanup) => cleanup());
  routeAvatarVoice("head-only", 1);
  for (const session of sessions) expect(session.setSpeechLevel).toHaveBeenLastCalledWith(0);
});
