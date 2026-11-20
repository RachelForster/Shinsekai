import type { Character } from "../../slices/characterTypes";
import type { ChatStat } from "../../slices/chatTypes";
import type { Background } from "../../slices/workspaceTypes";
import { importCharPackage } from "./charPackageCodec";

// Bundled via Vite static URL imports so paths resolve cleanly under relative subpaths (e.g. /toy/<slug>/)
export const BUNDLED_HOSHINA_SPRITES = [
  {
    key: "hoshina_01_greeting",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_01_greeting.webp", import.meta.url).href,
  },
  {
    key: "hoshina_02_happy",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_02_happy.webp", import.meta.url).href,
  },
  {
    key: "hoshina_03_shy",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_03_shy.webp", import.meta.url).href,
  },
  {
    key: "hoshina_04_curious",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_04_curious.webp", import.meta.url).href,
  },
  {
    key: "hoshina_05_thoughtful",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_05_thoughtful.webp", import.meta.url).href,
  },
  {
    key: "hoshina_06_surprised",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_06_surprised.webp", import.meta.url).href,
  },
  {
    key: "hoshina_07_gentle",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_07_gentle.webp", import.meta.url).href,
  },
  {
    key: "hoshina_08_wink",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_08_wink.webp", import.meta.url).href,
  },
  {
    key: "hoshina_09_pout",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_09_pout.webp", import.meta.url).href,
  },
  {
    key: "hoshina_10_serious",
    url: new URL("../../../../../../assets/starter/hoshina/hoshina_10_serious.webp", import.meta.url).href,
  },
] as const;

export const BUNDLED_STARTER_SPRITE_URL = BUNDLED_HOSHINA_SPRITES[0].url;

export const BUNDLED_STARTER_BG_URL = new URL(
  "../../../../../../assets/starter/hoshina/observatory_bg.webp",
  import.meta.url,
).href;

export const STARTER_HOSHINA_PORTRAIT_CROP = { x: 0.5, y: 0.27, zoom: 1.65 } as const;

const bundledPresetCharUrls = import.meta.glob<string>("../../../../../presets/*.char", {
  eager: true,
  import: "default",
  query: "?url",
});

export const STARTER_CHARACTER_NAME = "星奈";
export const STARTER_BACKGROUND_NAME = "星海观测台";

export function resolveBundledStarterAssetUrl(rawPath: string): string | null {
  if (!rawPath) return null;
  const clean = rawPath.trim().replace(/\\/g, "/");
  if (!clean || clean.startsWith("data:") || clean.startsWith("blob:")) {
    return null;
  }

  const fileName = clean.split(/[?#]/)[0].split("/").pop() ?? "";
  if (!fileName) return null;

  if (/^present_example(?:-[a-z0-9_-]{6,16})?\.[a-z]+$/i.test(fileName)) {
    return BUNDLED_STARTER_SPRITE_URL;
  }
  if (
    (!/banner|icon/i.test(fileName) && /^shinsekai(?:-[a-z0-9_-]{6,12})?\.png$/i.test(fileName)) ||
    /^observatory_bg(?:-[a-z0-9_-]{6,12})?\.[a-z]+$/i.test(fileName)
  ) {
    return BUNDLED_STARTER_BG_URL;
  }
  for (const item of BUNDLED_HOSHINA_SPRITES) {
    const pattern = new RegExp(`^${item.key}(?:-[a-z0-9_-]{6,12})?\\.(?:webp|png|jpe?g)$`, "i");
    if (pattern.test(fileName)) {
      return item.url;
    }
  }
  return null;
}

export function createStarterCharacter(): Character {
  return {
    name: STARTER_CHARACTER_NAME,
    color: "#f472b6",
    sprite_prefix: "starter_hoshina",
    avatar_type: "static",
    avatars: {},
    portrait_crop: { ...STARTER_HOSHINA_PORTRAIT_CROP },
    sprites: BUNDLED_HOSHINA_SPRITES.map((item) => ({
      path: item.url,
      group: "常服",
      portrait_crop: { ...STARTER_HOSHINA_PORTRAIT_CROP },
    })),
    sprite_groups: ["常服"],
    default_sprite_group: "常服",
    fallback_to_default_group: true,
    sprite_scale: 1,
    emotion_tags: [
      "立绘 1：微笑问候，轻抬右手挥手打招呼",
      "立绘 2：开心欢笑，眉眼弯弯元气喜悦",
      "立绘 3：害羞脸红，眼神微偏含蓄浅笑",
      "立绘 4：好奇倾听，眼睛发亮专注期待",
      "立绘 5：若有所思，轻点下巴安静思索",
      "立绘 6：惊讶睁眼，意外惊喜睁大双眸",
      "立绘 7：温柔安慰，双手轻合暖心倾听",
      "立绘 8：得意眨眼，俏皮灵动自信微笑",
      "立绘 9：小委屈鼓脸，脸颊微鼓撒娇嘟嘴",
      "立绘 10：认真讲解，竖起食指专注引导说明",
    ].join("\n"),
    character_brief: "新世界观测站的引导员，性格温柔灵动，善于倾听旅人的故事。",
    character_setting: [
      "姓名：星奈",
      "身份：新世界观测站的向导少女，负责迎接刚抵达此地的旅人，并帮忙校准「星海之声（AI 与语音）」。",
      "外貌特征：粉色及腰长发扎着左右双半丸子头，丸子头下方各垂一条带小金星发圈的细编发，点缀金色星星发饰，右手腕戴着金色双链星星手环，身穿纯白蝴蝶结领薄纱连衣裙。",
      "性格：温柔、细致又带有一点小调皮，喜欢收集旅人在不同世界见过的风景与记忆。",
      "说话风格：轻快自然，富有互动感；会在合适时机给出贴心的舞台演出与选项互动。",
    ].join("\n"),
    relation_graph: { nodes: [{ key: STARTER_CHARACTER_NAME }], edges: [] },
    gpt_model_path: "",
    sovits_model_path: "",
    refer_audio_path: "",
    prompt_text: "",
    prompt_lang: "",
    speech_speed: 1,
    speech_volume: 1,
    pronunciation_map: {},
  };
}

export function createStarterBackground(): Background {
  return {
    name: STARTER_BACKGROUND_NAME,
    sprite_prefix: "starter_observatory",
    sprites: [{ path: BUNDLED_STARTER_BG_URL }],
    bg_tags: "场景 1：新世界星海观测台，玻璃穹顶下的璀璨星河与星盘露台\n",
    bgm_list: [],
    bgm_tags: "",
  };
}

export function upgradeStarterPresetsInPlace(characters: Character[], backgrounds: Background[]): boolean {
  let mutated = false;
  const starterChar = createStarterCharacter();
  const starterBg = createStarterBackground();

  const hoshina = characters.find((c) => c.sprite_prefix === "starter_hoshina");
  if (hoshina) {
    const spritesMismatch =
      hoshina.sprites.length !== starterChar.sprites.length ||
      starterChar.sprites.some((target, idx) => hoshina.sprites[idx]?.path !== target.path);
    const needsUpgrade = spritesMismatch || hoshina.color === "#7dd3fc";

    if (needsUpgrade) {
      const previousSprites = hoshina.sprites ?? [];
      hoshina.sprites = starterChar.sprites.map((target, idx) => {
        const prev = previousSprites[idx];
        return {
          ...target,
          ...(prev?.voice_path ? { voice_path: prev.voice_path } : {}),
          ...(prev?.voice_text ? { voice_text: prev.voice_text } : {}),
          ...(prev?.voice_type ? { voice_type: prev.voice_type } : {}),
        };
      });
      hoshina.emotion_tags = starterChar.emotion_tags;
      hoshina.color = starterChar.color;
      hoshina.portrait_crop = { ...STARTER_HOSHINA_PORTRAIT_CROP };
      hoshina.character_setting = starterChar.character_setting;
      if (!hoshina.sprite_groups?.length) {
        hoshina.sprite_groups = [...(starterChar.sprite_groups ?? [])];
      }
      if (!hoshina.default_sprite_group) {
        hoshina.default_sprite_group = starterChar.default_sprite_group;
      }
      mutated = true;
    }
  }

  const observatory = backgrounds.find((b) => b.sprite_prefix === "starter_observatory");
  if (!observatory) {
    backgrounds.push(starterBg);
    mutated = true;
  } else if (observatory.sprites?.[0]?.path !== BUNDLED_STARTER_BG_URL) {
    observatory.sprites = starterBg.sprites.map((item) => ({ ...item }));
    observatory.bg_tags = starterBg.bg_tags;
    mutated = true;
  }

  return mutated;
}

export async function loadBundledPresets(existingCharacters: Character[]): Promise<{
  characters: Character[];
  backgrounds: Background[];
}> {
  const characters: Character[] = [];
  const usedNames = new Set(existingCharacters.map((c) => c.name));

  for (const [, assetUrl] of Object.entries(bundledPresetCharUrls).sort(([a], [b]) => a.localeCompare(b))) {
    if (typeof fetch === "undefined") break;
    try {
      const response = await fetch(assetUrl);
      if (!response.ok) continue;
      const bytes = new Uint8Array(await response.arrayBuffer());
      const imported = await importCharPackage(bytes, [...existingCharacters, ...characters]);
      for (const item of imported) {
        if (!usedNames.has(item.name)) {
          characters.push(item);
          usedNames.add(item.name);
        }
      }
    } catch {
      // Skip invalid optional build-time .char asset and fall back to starter character
    }
  }

  if (!characters.length && !usedNames.has(STARTER_CHARACTER_NAME)) {
    characters.push(createStarterCharacter());
  }

  return {
    characters,
    backgrounds: [createStarterBackground()],
  };
}

export interface PrologueSegment {
  speaker: string;
  speech: string;
  spriteIndex: number;
  narration?: boolean;
}

export interface PrologueStepResult {
  nextStepId: string;
  completed: boolean;
  segments: PrologueSegment[];
  options: string[];
  stats: ChatStat[];
}

export function createInitialPrologueState(characterName: string): {
  stepId: string;
  segments: PrologueSegment[];
  options: string[];
  stats: ChatStat[];
} {
  return {
    stepId: "intro_0",
    segments: [
      {
        speaker: "NARR",
        speech: "星海的微风穿过观测台的玻璃穹顶，光点在舞台中央凝聚成清晰的身影。",
        spriteIndex: 0,
        narration: true,
      },
      {
        speaker: characterName,
        speech:
          "欢迎来到「新世界」交互舞台！哪怕你现在还没有填写任何 API Key，也可以先点击下方选项体验立绘演出、分支剧情与好感度变化；点右上角「AI / 语音配置」填入 API Key 后，就能立刻和我展开无限自由对话啦～",
        spriteIndex: 0,
      },
    ],
    options: ["四处看看，这里都可以做什么？", "我有自己的角色卡，怎么导入这里？", "我想直接配置 API Key 开启自由对话！"],
    stats: [
      { icon: "heart", label: "好感度", value: 20, max: 100 },
      { icon: "sparkles", label: "同步率", value: 35, max: 100 },
    ],
  };
}

export function advancePrologueStep(
  stepId: string,
  userInput: string,
  characterName: string,
): PrologueStepResult {
  const normalized = userInput.trim();

  if (normalized.includes("重新体验") || normalized.includes("序章")) {
    const initial = createInitialPrologueState(characterName);
    return {
      nextStepId: initial.stepId,
      completed: false,
      segments: initial.segments,
      options: initial.options,
      stats: initial.stats,
    };
  }

  if (stepId === "intro_0") {
    if (normalized.includes("导入") || normalized.includes("角色")) {
      return {
        nextStepId: "intro_import_1",
        completed: false,
        segments: [
          {
            speaker: characterName,
            speech:
              "太棒了！点击右上角「AI / 语音配置」或进入「工作台 -> 角色」页面，就能直接从手机/电脑相册导入桌面版导出的 `.char` 角色包（连同动态立绘、口型同步和参考音频一起保存进浏览器本地），也可以当场新建属于你的原创角色！",
            spriteIndex: 9,
          },
          {
            speaker: characterName,
            speech: "导入完的角色还能随时再导出成标准 `.char` 带回电脑端，全过程只在你的设备本地保存，不会上传服务器哦。",
            spriteIndex: 6,
          },
        ],
        options: ["听起来很棒！那语音和口型怎么开启？", "明白啦，去配一个免费的 AI 对话 Key！"],
        stats: [
          { icon: "heart", label: "好感度", value: 32, max: 100 },
          { icon: "sparkles", label: "同步率", value: 58, max: 100 },
        ],
      };
    }

    if (normalized.includes("API") || normalized.includes("Key") || normalized.includes("自由对话")) {
      return {
        nextStepId: "intro_key_2",
        completed: true,
        segments: [
          {
            speaker: characterName,
            speech:
              "最推荐「硅基流动 SiliconFlow」或者 DeepSeek：点击右上角「AI / 语音配置」填入一个 Key，不仅能立刻解锁 DeepSeek / Qwen 自由对话，还能一键勾选用同一个 Key 驱动 CosyVoice2 实时语音和口型同步呢！",
            spriteIndex: 7,
          },
        ],
        options: ["重新体验互动序章"],
        stats: [
          { icon: "heart", label: "好感度", value: 40, max: 100 },
          { icon: "sparkles", label: "同步率", value: 75, max: 100 },
        ],
      };
    }

    return {
      nextStepId: "intro_explore_1",
      completed: false,
      segments: [
        {
          speaker: characterName,
          speech:
            "观测台支持全屏动态立绘、实时音频音量口型驱动、多分支选项、自动记忆压缩与时间线回溯～就算聊上几百轮，回看历史记录和重温回放也不会丢失任何一句话。",
          spriteIndex: 1,
        },
      ],
      options: ["那我该如何接入自由 AI 与云端配音？", "如果是手机版，还能连回电脑端吗？"],
      stats: [
        { icon: "heart", label: "好感度", value: 30, max: 100 },
        { icon: "sparkles", label: "同步率", value: 55, max: 100 },
      ],
    };
  }

  if (stepId === "intro_explore_1" || stepId === "intro_import_1") {
    const mobileMentioned = normalized.includes("手机") || normalized.includes("电脑");
    return {
      nextStepId: "intro_complete",
      completed: true,
      segments: [
        {
          speaker: characterName,
          speech: mobileMentioned
            ? "当然可以！在手机双模版下，外出时用你填的 API Key 和本地存储离线聊天；回到家或连上组网后，在「AI / 语音配置」里填上电脑端局域网地址，就能秒切电脑端满血本地语音与长期记忆，还能一键把电脑角色缓存到手机里带走～"
            : "只需点右上角「AI / 语音配置」，填入你的 LLM API Key（如硅基流动、DeepSeek、OpenAI 兼容接口）和云端语音 API Key（支持 CosyVoice2 参考音频克隆 / MiniMax / Qwen TTS），点击保存就能直接开口说话啦！",
          spriteIndex: mobileMentioned ? 3 : 9,
        },
        {
          speaker: "NARR",
          speech: "序章引导已完成！现在点击右上角「AI / 语音配置」填入 API Key 即可开启自由对话，或点击左侧「角色」切换 / 导入自定义角色。",
          spriteIndex: 6,
          narration: true,
        },
      ],
      options: ["重新体验互动序章"],
      stats: [
        { icon: "heart", label: "好感度", value: 45, max: 100 },
        { icon: "sparkles", label: "同步率", value: 85, max: 100 },
      ],
    };
  }

  return {
    nextStepId: "intro_complete",
    completed: true,
    segments: [
      {
        speaker: characterName,
        speech:
          `我听见你说：「${normalized.slice(0, 60)}」——我现在已经准备好进入自由对话阶段啦！不过需要先点右上角「AI / 语音配置」填入一个 LLM API Key，才能唤醒完整的星海语言核心哦～`,
        spriteIndex: 4,
      },
    ],
    options: ["重新体验互动序章"],
    stats: [
      { icon: "heart", label: "好感度", value: 45, max: 100 },
      { icon: "sparkles", label: "同步率", value: 85, max: 100 },
    ],
  };
}
