import { beforeEach, expect, it, vi } from "vitest";
import { getConversationSession } from "../../../entities/chat/repository";

const prepare = vi.hoisted(() => vi.fn());
vi.mock("../../../shared/platform/platform", () => ({
  getPlatform: () => ({ chat: { prepareConversation: prepare } }),
}));
beforeEach(() => vi.resetAllMocks());

it("restores top-level story options including explicit false and zero values", async () => {
  const options = {
    useCot: false,
    useEffect: false,
    useChoice: false,
    useNarration: false,
    useTranslation: false,
    useStat: true,
    voiceLanguage: "en",
    maxSpeechChars: 80,
    maxDialogItems: 0,
    characterPromptMode: "compact",
    primaryCharacters: ["Alice"],
    enableMobileAccess: true,
  };
  prepare.mockResolvedValue({
    ...options,
    characters: ["Alice", "Bob"],
    historyPath: "/saved",
    templateId: "",
    backgroundName: "Room",
  });
  expect(await getConversationSession("story")).toMatchObject({ ...options, selectedCharacters: ["Alice", "Bob"] });
});

it("prefers saved editor options and uses backend defaults for older records", async () => {
  prepare.mockResolvedValue({
    characters: [],
    templateId: "",
    backgroundName: "",
    historyPath: "/saved",
    voiceLanguage: "en",
    editorSession: { useCot: true, maxSpeechChars: 120 },
  });
  expect(await getConversationSession("chat")).toMatchObject({
    useCot: true,
    maxSpeechChars: 120,
    voiceLanguage: "en",
    useStat: true,
  });
  prepare.mockResolvedValue({ characters: [], templateId: "", backgroundName: "", historyPath: "/saved" });
  expect(await getConversationSession("legacy")).toMatchObject({ useCot: false, useStat: true });
});
