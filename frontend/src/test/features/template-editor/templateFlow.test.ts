import { describe, expect, it } from "vitest";

import {
  synchronizeTemplateLaunchSessionWithSnapshot,
  templateGenerationKey,
} from "../../../features/template-editor/templateFlow";
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

describe("template generation key", () => {
  const input: Parameters<typeof templateGenerationKey>[0] = {
    characters: ["Player", "NPC"],
    characterPromptMode: "compact",
    primaryCharacters: ["NPC"],
    mediaSelectionMode: "semantic",
    playerCharacter: "Player",
    readPlayerSpeech: true,
    allowPlayerDialogue: false,
  };

  it("retains the existing fingerprint format used when restoring a session", () => {
    expect(templateGenerationKey(input)).toBe("Player\nNPC\n--compact\nNPC\n--semantic\n--Player\n--true\n--false");
  });

  it("gives legacy and explicitly defaulted settings the same key", () => {
    expect(templateGenerationKey({ characters: ["NPC"] })).toBe(
      templateGenerationKey({
        characters: ["NPC"],
        primaryCharacters: [],
        mediaSelectionMode: "indexed",
        playerCharacter: "",
        readPlayerSpeech: false,
        allowPlayerDialogue: true,
      }),
    );
  });

  const changes: Partial<typeof input>[] = [
    { characters: ["NPC", "Player"] },
    { characterPromptMode: "full" },
    { primaryCharacters: ["Player"] },
    { mediaSelectionMode: "indexed" },
    { playerCharacter: "NPC" },
    { readPlayerSpeech: false },
    { allowPlayerDialogue: true },
  ];
  it.each(changes)("regenerates when a generation-relevant setting changes: %j", (change) => {
    expect(templateGenerationKey({ ...input, ...change })).not.toBe(templateGenerationKey(input));
  });
});

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
