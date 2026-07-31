import { describe, expect, it } from "vitest";

import { synchronizeChatLaunchPayloadWithSession } from "../../../features/template-editor/templateFlow";
import type { ChatLaunchPayload, TemplateLaunchSession } from "../../../shared/platform/types";

describe("synchronizeChatLaunchPayloadWithSession", () => {
  it("preserves exact path identities for backend validation", () => {
    const payload = {
      backgroundName: "",
      characters: [],
      historyPath: "",
      initSpritePath: "",
      resetHistory: false,
      roomId: "",
      scenario: "",
      system: "",
      templateId: "",
      templateName: "",
      useCg: false,
    } satisfies ChatLaunchPayload;
    const session = {
      background: "",
      effectNames: [],
      filenameStub: "Template",
      historyPath: " data/chat_history/session ",
      initSpritePath: " data/sprites/initial.png ",
      maxDialogItems: 20,
      maxSpeechChars: 200,
      roomId: "",
      scenario: "",
      selectedCharacters: [],
      system: "",
      templateFileDropdown: "template",
      useCg: false,
      useChoice: false,
      useCot: false,
      useEffect: false,
      useNarration: false,
      useStat: false,
      useTranslation: false,
      voiceLanguage: "ja",
    } satisfies TemplateLaunchSession;

    const synchronized = synchronizeChatLaunchPayloadWithSession(payload, session);

    expect(synchronized.historyPath).toBe(session.historyPath);
    expect(synchronized.initSpritePath).toBe(session.initSpritePath);
  });
});
