// @vitest-environment node
import ts from "typescript";
import { describe, expect, it } from "vitest";

const CJK_PATTERN = /[\u3400-\u9fff\u3040-\u30ff]/;

const EXEMPT_PATH_PREFIXES = [
  "shared/i18n/messages/",
  "modules/character-visual/adapters/mmd/",
  "features/release-highlights/releases/",
] as const;

const EXEMPT_FILES = new Set<string>([
  "shared/platform/sampleData.ts",
  "shared/platform/previewStoryGraph.ts",
  "shared/constants.ts",
  "shared/playerCharacterOptions.ts",
  "features/chat-stage/state/legacySnapshotCompat.ts",
  "shared/platform/standalone/ai/generatedTemplateLocales.json",
]);

/**
 * Ratchet allowlist of existing frontend files with non-comment CJK literals.
 * Never add new files here; remove entries as each module is migrated to i18n.
 */
const LOCKED_FRONTEND_CJK_ALLOWLIST: readonly string[] = [
  "app/shell/AppShell.tsx",
  "app/shell/SidebarNav.tsx",
  "entities/config/schema.ts",
  "features/api-settings/AdapterExtraForm.tsx",
  "features/api-settings/ApiSettingsPage.tsx",
  "features/api-settings/apiSettingsUtils.ts",
  "features/background-manager/BackgroundManagerPage.tsx",
  "features/character-editor/CharacterBasicSection.tsx",
  "features/character-editor/CharacterEditorPage.tsx",
  "features/character-editor/SpriteGenerationPage.tsx",
  "features/character-editor/characterEditorUtils.ts",
  "features/character-editor/useSpriteGeneration.ts",
  "features/character-editor/useSpriteMouths.ts",
  "features/chat-stage/components/HistoryDialog.tsx",
  "features/chat-stage/components/TopStageTools.tsx",
  "features/chat-stage/state/text.ts",
  "features/effect-manager/EffectManagerPage.tsx",
  "features/logs/LogsPage.tsx",
  "features/music-cover/MusicCoverPage.tsx",
  "features/onboarding/onboardingCopy.ts",
  "features/onboarding/steps/PluginSetupPanel.tsx",
  "features/plugin-manager/PluginManagerPage.tsx",
  "features/runtime-mode/RuntimeModeDialog.tsx",
  "features/system-settings/SystemSettingsPage.tsx",
  "features/template-editor/TemplateEditorPage.tsx",
  "shared/platform/agentPreviewPlatform.ts",
  "shared/platform/browserPreviewPlatform.ts",
  "shared/platform/httpTransport.ts",
  "shared/platform/slices/characterPreviewPlatform.ts",
  "shared/platform/slices/chatPreviewPlatform.ts",
  "shared/platform/slices/configPreviewPlatform.ts",
  "shared/platform/slices/pluginPreviewPlatform.ts",
  "shared/platform/slices/previewContext.ts",
  "shared/platform/slices/workspacePreviewPlatform.ts",
  "shared/platform/standalone/ai/adapters/llm/claudeAdapter.ts",
  "shared/platform/standalone/ai/adapters/llm/openaiCompatibleAdapter.ts",
  "shared/platform/standalone/ai/adapters/llm/presets.ts",
  "shared/platform/standalone/ai/adapters/registry.ts",
  "shared/platform/standalone/ai/adapters/tts/browserSpeechAdapter.ts",
  "shared/platform/standalone/ai/adapters/tts/gptSovitsCloudAdapter.ts",
  "shared/platform/standalone/ai/adapters/tts/minimaxTtsAdapter.ts",
  "shared/platform/standalone/ai/adapters/tts/openaiSpeechAdapter.ts",
  "shared/platform/standalone/ai/adapters/tts/qwenTtsAdapter.ts",
  "shared/platform/standalone/ai/dialogOutputParser.ts",
  "shared/platform/standalone/ai/httpClient.ts",
  "shared/platform/standalone/ai/standaloneChatTurn.ts",
  "shared/platform/standalone/ai/templateGenerator.ts",
  "shared/platform/standalone/index.ts",
  "shared/platform/standalone/packages/charPackageCodec.ts",
  "shared/platform/standalone/packages/presetLoader.ts",
  "shared/platform/standalone/storage/sessionStore.ts",
  "shared/platform/standalone/storage/vfsBlobRegistry.ts",
  "shared/platform/storyPreviewPlatform.ts",
  "shared/ui/ErrorBoundary.tsx",
  "shared/ui/PathPickerDialog.tsx",
  "shared/ui/TaskProgress.tsx",
];

const sources = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>("../../{app,entities,features,modules,shared}/**/*.{ts,tsx}", {
      eager: true,
      import: "default",
      query: "?raw",
    }),
  ).map(([filePath, code]) => [filePath.replace(/^\.\.\/\.\.\//, ""), code]),
);

function isExempt(file: string): boolean {
  if (EXEMPT_FILES.has(file)) {
    return true;
  }
  return EXEMPT_PATH_PREFIXES.some((prefix) => file.startsWith(prefix));
}

function hasRuntimeCjkLiteral(file: string, code: string): boolean {
  const scriptKind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, scriptKind);
  let found = false;

  const visit = (node: ts.Node) => {
    if (found) {
      return;
    }
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node)
    ) {
      if (CJK_PATTERN.test(node.text)) {
        found = true;
        return;
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  return found;
}

describe("frontend i18n hardcode ratchet", () => {
  it("keeps hardcoded CJK literals strictly within the shrinking allowlist", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(100);

    const actual = Object.entries(sources)
      .filter(([file, code]) => !isExempt(file) && hasRuntimeCjkLiteral(file, code))
      .map(([file]) => file)
      .sort();

    const expected = [...LOCKED_FRONTEND_CJK_ALLOWLIST].sort();
    const allowlistSet = new Set(expected);
    const actualSet = new Set(actual);

    const unexpected = actual.filter((file) => !allowlistSet.has(file));
    const stale = expected.filter((file) => !actualSet.has(file));

    expect(
      { stale, unexpected },
      `Update LOCKED_FRONTEND_CJK_ALLOWLIST only by removing migrated files.\nActual (${actual.length}):\n${JSON.stringify(actual, null, 2)}`,
    ).toEqual({ stale: [], unexpected: [] });
  });
});
