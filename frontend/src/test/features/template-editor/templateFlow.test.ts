import { describe, expect, it } from "vitest";

import { synchronizeTemplateLaunchSessionWithSnapshot } from "../../../features/template-editor/templateFlow";
import type { ChatSnapshot, TemplateLaunchSession } from "../../../shared/platform/types";

const session: TemplateLaunchSession = {
  background: "room",
  effectNames: [],
  filenameStub: "Default",
  historyPath: "/history/previous",
  initSpritePath: "",
  maxDialogItems: 0,
  maxSpeechChars: 0,
  roomId: "",
  scenario: "scene",
  selectedCharacters: ["Nanami"],
  system: "system",
  templateFileDropdown: "default",
  useCg: false,
  useChoice: false,
  useCot: false,
  useEffect: false,
  useNarration: false,
  useStat: false,
  useTranslation: false,
  voiceLanguage: "ja",
};

function snapshot(historyPath: string): ChatSnapshot {
  return {
    dialogText: "",
    historyPath,
    inputDraft: "",
    options: [],
    sprites: [],
    status: "idle",
  };
}

describe("synchronizeTemplateLaunchSessionWithSnapshot", () => {
  it("keeps the rollback history when initialization stops for a missing dependency", () => {
    const dependencySnapshot = {
      ...snapshot("/history/quick-restart-candidate"),
      runtimeDependencyError: { message: "Missing mem0", moduleName: "mem0", packageName: "mem0ai" },
      status: "error" as const,
    };

    expect(synchronizeTemplateLaunchSessionWithSnapshot(session, dependencySnapshot)).toBe(session);
  });

  it("accepts the backend-selected history after successful initialization", () => {
    expect(synchronizeTemplateLaunchSessionWithSnapshot(session, snapshot("/history/confirmed"))).toEqual({
      ...session,
      historyPath: "/history/confirmed",
    });
  });
});
