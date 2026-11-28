import type { QueryClient } from "@tanstack/react-query";

const REFRESH_QUERY_KEY_MAP: Record<string, readonly unknown[]> = {
  agent: ["agent"],
  api: ["config"],
  backgrounds: ["backgrounds"],
  "character-relations": ["character-relations"],
  characters: ["characters"],
  chat: ["chat"],
  config: ["config"],
  effects: ["effects"],
  novel: ["novel"],
  plugins: ["plugins"],
  sections: ["plugins", "sections"],
  "sidebar-pages": ["plugins", "sidebar-pages"],
  "slot-contributions": ["plugins", "slot-contributions"],
  "story-library": ["story-library"],
  system: ["config"],
  templates: ["templates"],
};

export function invalidatePluginRefreshTargets(queryClient: QueryClient, targets: readonly string[] | undefined) {
  if (!targets?.length) {
    return;
  }
  const seen = new Set<string>();
  for (const rawTarget of targets) {
    const key = String(rawTarget || "")
      .trim()
      .toLowerCase();
    if (!key) {
      continue;
    }
    const queryKey = REFRESH_QUERY_KEY_MAP[key];
    if (!queryKey) {
      continue;
    }
    const signature = queryKey.join("\0");
    if (seen.has(signature)) {
      continue;
    }
    seen.add(signature);
    void queryClient.invalidateQueries({ queryKey });
  }
}
