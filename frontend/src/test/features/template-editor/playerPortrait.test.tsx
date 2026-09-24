import { describe, expect, it } from "vitest";
import { portraitGeometry } from "../../../shared/components/Portrait";
import { applyPortraitCrop } from "../../../features/template-editor/PlayerCharacterSettings";
import { playerPortraitForDialog } from "../../../features/chat-stage/state/text";
import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import {
  buildTemplateLaunchSession,
  synchronizeChatLaunchPayloadWithSession,
} from "../../../features/template-editor/templateFlow";

describe("player portrait", () => {
  it("shows only for player speech and narration mentioning the player", () => {
    const portrait = { characterName: "水岛 神羽", url: "face.png", crop: { x: 0.5, y: 0.2, zoom: 1 } };
    expect(playerPortraitForDialog(portrait, "水岛 神羽", "我才不要")).toBe(portrait);
    expect(playerPortraitForDialog(portrait, "NARR", "水岛神羽摊开手。")).toBe(portrait);
    expect(playerPortraitForDialog(portrait, "旁白", "阳明拉住水岛 神羽的手。")).toBe(portrait);
    expect(playerPortraitForDialog(portrait, "阳明", "水岛神羽，小心！")).toBeNull();
    expect(playerPortraitForDialog(portrait, "NARR", "阳明望向窗外。")).toBeNull();
    expect(playerPortraitForDialog(portrait, undefined, "水岛神羽")).toBeNull();
  });
  it("keeps a square crop inside both wide and tall images", () => {
    for (const [width, height] of [
      [400, 1200],
      [1200, 400],
    ]) {
      for (const x of [0, 0.5, 1])
        for (const y of [0, 0.5, 1]) {
          const crop = portraitGeometry(width, height, { x, y, zoom: 2 });
          expect(crop.side).toBe(200);
          expect(crop.left).toBeGreaterThanOrEqual(0);
          expect(crop.top).toBeGreaterThanOrEqual(0);
          expect(crop.left + crop.side).toBeLessThanOrEqual(width);
          expect(crop.top + crop.side).toBeLessThanOrEqual(height);
        }
    }
  });

  it("keeps each sprite crop when switching between sprites", () => {
    const character = {
      name: "神羽",
      color: "#fff",
      sprite_prefix: "神羽",
      sprites: [{ path: "one.png" }, { path: "two.png" }],
      character_setting: "",
      sprite_scale: 1,
      emotion_tags: "",
      speech_speed: 1,
      speech_volume: 1,
      pronunciation_map: {},
    };
    const first = { x: 0.2, y: 0.3, zoom: 2 };
    const second = { x: 0.7, y: 0.6, zoom: 3 };

    const afterFirst = applyPortraitCrop(character, 0, true, first);
    const afterSecond = applyPortraitCrop(afterFirst, 1, true, second);

    expect(afterSecond.sprites[0].portrait_crop).toEqual(first);
    expect(afterSecond.sprites[1].portrait_crop).toEqual(second);
  });

  it("updates player expression without replacing dialogue or stage sprites", () => {
    const initial = { ...emptyChatState, dialogText: "阳明的台词", characterName: "阳明" };
    const next = chatStageReducer(initial, {
      type: "event",
      event: {
        v: 1,
        seq: 1,
        ts: 1,
        type: "player.portrait.show",
        characterName: "神羽",
        url: "face.png",
        crop: { x: 0.5, y: 0.2, zoom: 2 },
      },
    });
    expect(next.dialogText).toBe(initial.dialogText);
    expect(next.characterName).toBe("阳明");
    expect(next.sprites).toEqual(initial.sprites);
    expect(next.playerPortrait?.url).toBe("face.png");
    const background = chatStageReducer(next, {
      type: "event",
      event: { v: 1, seq: 2, ts: 2, type: "background.change", url: "bg.png" },
    });
    expect(background.playerPortrait).toEqual(next.playerPortrait);
  });

  it("passes the player identity and voice option through saved sessions", () => {
    const session = buildTemplateLaunchSession({
      backgroundName: "背景",
      draft: { id: "", name: "test", content: "", path: "", updatedAt: "", scenario: "", system: "" },
      mobileAccessEnabled: false,
      mediaSelectionMode: "indexed",
      selectedTemplateId: "",
      selectedCharacters: ["神羽", "阳明"],
      playerCharacter: "神羽",
      readPlayerSpeech: true,
      runtime: {
        historyPath: "history",
        initSpritePath: "",
        maxDialogItems: 0,
        maxSpeechChars: 0,
        roomId: "",
        voiceLanguage: "zh",
      },
      options: {
        useCg: false,
        useChoice: true,
        useCot: false,
        useEffect: false,
        useNarration: true,
        useStat: false,
        useTranslation: false,
      },
    });
    const payload = synchronizeChatLaunchPayloadWithSession(
      { backgroundName: "", characters: [], historyPath: "", templateId: "" },
      session,
    );
    expect(payload.playerCharacter).toBe("神羽");
    expect(payload.readPlayerSpeech).toBe(true);
  });
});
