import type { Character } from "../../slices/characterTypes";
import type { CharacterOutfitState, ChatLaunchPayload, ChatStat } from "../../slices/chatTypes";

export interface StandalonePromptContext {
  characters: Character[];
  payload: ChatLaunchPayload;
  outfits?: Record<string, CharacterOutfitState>;
  stats?: ChatStat[];
  userDisplayName?: string;
}

function formatCharacterBlock(character: Character, outfitState?: CharacterOutfitState): string {
  const tagsLines = (character.emotion_tags || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const spriteList = character.sprites ?? [];
  const numberedSprites = spriteList.map((sprite, idx) => {
    const tagLine = tagsLines[idx] || `立绘 ${idx + 1}：默认表情`;
    const groupText = sprite.group ? ` [服装组: ${sprite.group}]` : "";
    return `${idx + 1}. ${tagLine}${groupText}`;
  });

  const parts: string[] = [
    `### 角色「${character.name}」`,
    character.character_brief ? `简介：${character.character_brief}` : "",
    character.character_setting ? `详细设定：\n${character.character_setting}` : "",
    character.sprite_groups?.length
      ? `可用服装组：${character.sprite_groups.join("、")}（当前服装：${outfitState?.activeGroup || character.default_sprite_group || "默认"}${outfitState?.locked ? "，已锁定请勿自动更换" : ""}）`
      : "",
    numberedSprites.length ? `可用立绘编号（1..${numberedSprites.length}）：\n${numberedSprites.join("\n")}` : "",
  ];

  return parts.filter(Boolean).join("\n");
}

export function buildStandaloneDialogSystemPrompt(ctx: StandalonePromptContext): string {
  const { characters, payload, outfits, stats, userDisplayName } = ctx;
  const charSections = characters.map((char) => formatCharacterBlock(char, outfits?.[char.name]));

  const rules: string[] = [
    `你正在驱动视觉小说交互舞台（Shinsekai）。玩家名：${userDisplayName || payload.playerCharacter || "旅人"}。`,
    "请严格依据设定扮演以下角色，一次回复可包含 1~" +
      String(Math.max(2, Math.min(6, payload.maxDialogItems ?? 4))) +
      " 条连贯对话。",
    "【重要输出格式】请只输出一个合法 JSON 对象（不要包含 Markdown 以外的解释文字）：",
    `{
  "dialog": [
    {
      "character_name": "角色名",
      "speech": "角色说的话",
      "sprite": 1,
      "outfit": ""${payload.useTranslation ? ',\n      "translate": "中文译文"' : ""}
    }${payload.useNarration !== false ? ',\n    { "character_name": "NARR", "speech": "简洁的动作或环境旁白" }' : ""}${
      payload.useStat
        ? ',\n    { "character_name": "STAT", "stats": [{ "label": "好感度", "value": 30, "max": 100, "icon": "heart" }] }'
        : ""
    }${
      payload.useChoice !== false
        ? ',\n    { "character_name": "CHOICE", "options": ["简短互动选项A", "简短互动选项B"] }'
        : ""
    }
  ]
}`,
    "- `sprite` 请填写对应的立绘编号整数（1 开始）。",
    '- 若需要提供玩家选择，在 `dialog` 末尾附加一条 `character_name: "CHOICE"`。',
  ];

  if (payload.voiceLanguage && payload.voiceLanguage !== "Chinese" && payload.voiceLanguage !== "中文") {
    rules.push(`- 角色台词 \`speech\` 请优先使用 ${payload.voiceLanguage}，并在 \`translate\` 字段附带流畅中文翻译。`);
  }
  if (payload.maxSpeechChars && payload.maxSpeechChars > 0) {
    rules.push(`- 单条台词长度尽量控制在 ${payload.maxSpeechChars} 字以内。`);
  }
  if (payload.scenario?.trim()) {
    rules.push(`\n【场景剧本与背景设定】\n${payload.scenario.trim()}`);
  }
  if (payload.system?.trim()) {
    rules.push(`\n【额外导演提示】\n${payload.system.trim()}`);
  }
  if (stats?.length) {
    const statSummary = stats.map((s) => `${s.label}: ${s.value}${s.max ? `/${s.max}` : ""}`).join("，");
    rules.push(`\n【当前舞台数值】${statSummary}`);
  }

  return [...rules, "\n【登场角色档案】", ...charSections].filter(Boolean).join("\n\n");
}
