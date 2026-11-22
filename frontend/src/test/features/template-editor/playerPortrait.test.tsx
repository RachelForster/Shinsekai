import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  Portrait,
  portraitGeometry,
  portraitViewportGeometry,
  resolveSpritePortraitCrop,
} from "../../../shared/components/Portrait";
import { PortraitCropDialog } from "../../../shared/components/PortraitCropDialog";
import { applyPortraitCrop } from "../../../features/template-editor/PlayerCharacterSettings";
import { playerPortraitForDialog } from "../../../features/chat-stage/state/text";
import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import {
  buildTemplateLaunchSession,
  synchronizeChatLaunchPayloadWithSession,
} from "../../../features/template-editor/templateFlow";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

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
      avatar_type: "static",
      avatars: {},
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

  it.each([undefined, true, false])("keeps player AI mode %s in saved sessions", (allowPlayerDialogue) => {
    const session = buildTemplateLaunchSession({
      backgroundName: "背景",
      draft: { id: "", name: "test", content: "", path: "", updatedAt: "", scenario: "", system: "" },
      mobileAccessEnabled: false,
      mediaSelectionMode: "indexed",
      selectedTemplateId: "",
      selectedCharacters: ["神羽", "阳明"],
      playerCharacter: "神羽",
      readPlayerSpeech: true,
      allowPlayerDialogue,
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
    expect(session.allowPlayerDialogue).toBe(allowPlayerDialogue ?? true);
    expect(payload.allowPlayerDialogue).toBe(allowPlayerDialogue ?? true);
  });

  it("fits non-square card viewports without stretching and resolves sprite vs default crops", () => {
    const rectViewport = portraitViewportGeometry(600, 1200, { x: 0.5, y: 0.2, zoom: 2 }, 56 / 64);
    expect(rectViewport.width / rectViewport.height).toBeCloseTo(56 / 64, 5);
    expect(rectViewport.left).toBeGreaterThanOrEqual(0);
    expect(rectViewport.top).toBeGreaterThanOrEqual(0);
    expect(rectViewport.left + rectViewport.width).toBeLessThanOrEqual(600);
    expect(rectViewport.top + rectViewport.height).toBeLessThanOrEqual(1200);

    const character = {
      portrait_crop: { x: 0.4, y: 0.25, zoom: 1.5 },
      sprites: [{ path: "a.png" }, { path: "b.png", portrait_crop: { x: 0.7, y: 0.3, zoom: 2.5 } }],
    };
    expect(resolveSpritePortraitCrop(character, 0)).toEqual({ x: 0.4, y: 0.25, zoom: 1.5 });
    expect(resolveSpritePortraitCrop(character, 1)).toEqual({ x: 0.7, y: 0.3, zoom: 2.5 });
  });

  it("falls back cleanly on broken images and supports pointer drag, wheel zoom, sprite switch, and reset in PortraitCropDialog", () => {
    const { unmount } = render(<Portrait name="Mio" path="http://127.0.0.1:8787/broken.png" shape="circle" />);
    const img = screen.getByAltText("Mio");
    fireEvent.error(img);
    expect(document.querySelector(".portrait__fallback")).toHaveTextContent("M");
    unmount();

    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <I18nProvider language="en">
        <PortraitCropDialog
          character={{
            avatar_type: "static",
            avatars: {},
            character_setting: "",
            color: "#ffffff",
            emotion_tags: "Sprite 1: neutral\nSprite 2: smile\n",
            name: "Mio",
            portrait_crop: { x: 0.5, y: 0.2, zoom: 1.5 },
            pronunciation_map: {},
            speech_speed: 1,
            speech_volume: 1,
            sprite_prefix: "mio",
            sprite_scale: 1,
            sprites: [{ path: "http://127.0.0.1:8787/mio-1.png" }, { path: "http://127.0.0.1:8787/mio-2.png" }],
          }}
          initialSpriteIndex={0}
          onClose={onClose}
          onSave={onSave}
          open
        />
      </I18nProvider>,
    );

    const stage = document.querySelector<HTMLElement>(".portrait-crop-dialog__stage")!;
    Object.defineProperty(stage, "clientWidth", { configurable: true, value: 240 });
    const stageImg = stage.querySelector("img")!;
    Object.defineProperties(stageImg, { naturalWidth: { value: 600 }, naturalHeight: { value: 1200 } });
    fireEvent.load(stageImg);

    fireEvent.wheel(stage, { deltaY: -100 });
    fireEvent(
      stage,
      Object.assign(new MouseEvent("pointerdown", { bubbles: true, buttons: 1, clientX: 100, clientY: 100 }), {
        pointerId: 1,
      }),
    );
    fireEvent(
      stage,
      Object.assign(new MouseEvent("pointermove", { bubbles: true, buttons: 1, clientX: 130, clientY: 120 }), {
        pointerId: 1,
      }),
    );

    // Switch to sprite 2 and enable per-sprite crop
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: /mio-2\.png/ }));
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Apply only to this sprite (otherwise save as character default)",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reset crop" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledOnce();
    const saved = onSave.mock.calls[0][0];
    expect(saved.sprites[1].portrait_crop).toEqual({ x: 0.5, y: 0.2, zoom: 1 });
  });

  it("saves portrait_sprite_index when saveSelectedAsDefaultPortrait is enabled", () => {
    const onSave = vi.fn();
    render(
      <I18nProvider language="en">
        <PortraitCropDialog
          character={{
            avatar_type: "static",
            avatars: {},
            character_setting: "",
            color: "#ffffff",
            emotion_tags: "Sprite 1: neutral\nSprite 2: smile\n",
            name: "Mio",
            portrait_crop: { x: 0.5, y: 0.2, zoom: 1 },
            portrait_sprite_index: 0,
            pronunciation_map: {},
            speech_speed: 1,
            speech_volume: 1,
            sprite_prefix: "mio",
            sprite_scale: 1,
            sprites: [{ path: "http://127.0.0.1:8787/mio-1.png" }, { path: "http://127.0.0.1:8787/mio-2.png" }],
          }}
          initialSpriteIndex={0}
          onClose={vi.fn()}
          onSave={onSave}
          open
          saveSelectedAsDefaultPortrait
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "Expression sprite" }));
    fireEvent.click(screen.getByRole("option", { name: /mio-2\.png/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ portrait_sprite_index: 1 }));
  });
});
