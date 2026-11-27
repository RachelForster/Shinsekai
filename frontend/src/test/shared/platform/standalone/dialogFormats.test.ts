import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetPlatformForModeSwitch } from "../../../../shared/platform/platform";
import { sampleConfig } from "../../../../shared/platform/sampleData";
import { createStandalonePlatform } from "../../../../shared/platform/standalone";
import { clearAllStandaloneStorage, setKvConfig } from "../../../../shared/platform/standalone/storage/indexedDbStore";

describe("standalone dialog output format capability", () => {
  beforeEach(async () => {
    await clearAllStandaloneStorage();
    window.localStorage?.clear();
    resetPlatformForModeSwitch();
  });

  afterEach(() => {
    resetPlatformForModeSwitch();
  });

  it("exposes only json_v1 in standalone mode and normalizes starter state to json_v1", async () => {
    const platform = createStandalonePlatform({ target: "toy" });
    const formats = await platform.templates.listDialogFormats();
    expect(formats).toEqual([{ id: "json_v1", label: "JSON", builtin: true }]);

    const starterTemplates = await platform.templates.list();
    expect(starterTemplates.length).toBeGreaterThan(0);
    for (const item of starterTemplates) {
      expect(item.outputFormat).toBe("json_v1");
    }
    expect((await platform.templates.getSession())?.outputFormat).toBe("json_v1");

    const chars = await platform.characters.list();
    expect(chars.length).toBeGreaterThan(0);

    const generated = await platform.templates.generate({
      backgroundName: "透明场景",
      characters: [chars[0].name],
      name: "Test",
      outputFormat: "xml_v1",
      useChoice: true,
      useNarration: true,
      useStat: true,
    });
    expect(generated.outputFormat).toBe("json_v1");
  });

  it("normalizes persisted xml_v1 templates, sessions, and chat payloads to json_v1", async () => {
    await setKvConfig("app_config", structuredClone(sampleConfig));
    await setKvConfig("templates", [
      {
        id: "persisted-xml",
        name: "Persisted XML",
        content: "Scenario\n\nSystem",
        scenario: "Scenario",
        system: "System",
        outputFormat: "xml_v1",
        path: "",
        updatedAt: "2026-11-27",
      },
    ]);
    await setKvConfig("template_session", {
      background: "透明场景",
      effectNames: [],
      filenameStub: "persisted",
      historyPath: "./data/history/persisted.json",
      initSpritePath: "",
      maxDialogItems: 4,
      maxSpeechChars: 120,
      outputFormat: "xml_v1",
      roomId: "",
      scenario: "Scenario",
      selectedCharacters: [sampleConfig.characters[0].name],
      system: "System",
      templateFileDropdown: "persisted-xml",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: false,
      voiceLanguage: "ja",
    });

    const platform = createStandalonePlatform({ target: "toy" });
    const listed = await platform.templates.list();
    expect(listed[0]?.outputFormat).toBe("json_v1");
    expect((await platform.templates.getSession())?.outputFormat).toBe("json_v1");

    const savedTemplate = await platform.templates.save({
      ...listed[0],
      outputFormat: "xml_v1",
    });
    expect(savedTemplate.outputFormat).toBe("json_v1");

    const currentSession = (await platform.templates.getSession())!;
    const savedSession = await platform.templates.saveSession({
      ...currentSession,
      outputFormat: "xml_v1",
    });
    expect(savedSession.outputFormat).toBe("json_v1");

    await platform.chat.launch({
      backgroundName: "透明场景",
      characters: [sampleConfig.characters[0].name],
      editorSession: { ...currentSession, outputFormat: "xml_v1" },
      historyPath: "./data/history/persisted.json",
      outputFormat: "xml_v1",
      templateId: "persisted-xml",
    });
    const convs = await platform.chat.listConversations();
    const prepared = await platform.chat.prepareConversation(convs[0].sessionId || convs[0].id);
    expect(prepared.outputFormat).toBe("json_v1");
    expect(prepared.editorSession?.outputFormat).toBe("json_v1");
  });
});
