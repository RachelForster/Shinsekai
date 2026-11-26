import { tagContents } from "../../../assets/assetText";
import { DEFAULT_SPRITE_GROUP } from "../../../constants";
import type { Character, RelationEdge } from "../../slices/characterTypes";
import type { Effect } from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";

function catalogNameKey(name: string): string {
  return name.trim().toLowerCase();
}

function spriteGroupOf(group: string | null | undefined): string {
  return String(group ?? "").trim() || DEFAULT_SPRITE_GROUP;
}

function listNonEmptySpriteGroups(character: Character): string[] {
  const sprites = character.sprites ?? [];
  const present = new Set<string>();
  const presentOrder: string[] = [];
  for (const sprite of sprites) {
    const grp = spriteGroupOf(sprite.group);
    if (!present.has(grp)) {
      present.add(grp);
      presentOrder.push(grp);
    }
  }
  const configured = (character.sprite_groups ?? []).map((g) => spriteGroupOf(g));
  const ordered = configured.filter((g) => present.has(g));
  for (const grp of presentOrder) {
    if (!ordered.includes(grp)) ordered.push(grp);
  }
  return ordered;
}

function resolveDefaultSpriteGroup(character: Character): string {
  const present = listNonEmptySpriteGroups(character);
  const configured = String(character.default_sprite_group ?? "").trim();
  if (configured) {
    const norm = spriteGroupOf(configured);
    if (!present.length || present.includes(norm)) {
      return norm;
    }
  }
  if (!present.length || present.includes(DEFAULT_SPRITE_GROUP)) {
    return DEFAULT_SPRITE_GROUP;
  }
  return present[0];
}

export function characterSpriteCatalogText(
  character: Character,
  t: ReturnType<typeof createStandaloneTemplateTranslator>,
): string {
  const sprites = character.sprites ?? [];
  const nonEmptyGroups = listNonEmptySpriteGroups(character);
  if (nonEmptyGroups.length < 2) {
    return `${t("sprites_count", { name: character.name, n: sprites.length })}${character.emotion_tags ?? ""}\n\n`;
  }
  const defaultGroup = resolveDefaultSpriteGroup(character);
  const indices: number[] = [];
  sprites.forEach((sprite, idx) => {
    if (spriteGroupOf(sprite.group) === defaultGroup) {
      indices.push(idx);
    }
  });
  const tags = tagContents(character.emotion_tags ?? "", sprites.length);
  const filteredTags = indices.map((idx) => (tags[idx] ? `${idx + 1}:${tags[idx]}` : `${idx + 1}:`)).join(", ");
  return `${t("sprites_count", { name: character.name, n: indices.length })}${filteredTags}\n\n`;
}

function cleanInlineText(value: unknown): string {
  return String(value ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

export function buildRelationSectionText(
  characters: Character[],
  primaryNames: Set<string> | null,
  t: ReturnType<typeof createStandaloneTemplateTranslator>,
): string {
  const selectedKeys = new Set(characters.map((c) => catalogNameKey(c.name)));
  const blocks: string[] = [];

  for (const char of characters) {
    if (primaryNames !== null && !primaryNames.has(char.name)) continue;
    const graph = char.relation_graph;
    if (!graph?.edges?.length) continue;

    const filtered: RelationEdge[] = graph.edges
      .filter((edge) => {
        const srcKey = catalogNameKey(edge.source);
        const dstKey = catalogNameKey(edge.target);
        return (
          (selectedKeys.has(srcKey) || selectedKeys.has(dstKey)) &&
          (edge.content.trim().length > 0 || edge.temperature !== 0)
        );
      })
      .sort((a, b) => {
        const aBoth = selectedKeys.has(catalogNameKey(a.source)) && selectedKeys.has(catalogNameKey(a.target));
        const bBoth = selectedKeys.has(catalogNameKey(b.source)) && selectedKeys.has(catalogNameKey(b.target));
        if (aBoth !== bBoth) return aBoth ? -1 : 1;
        if (a.source !== b.source) return a.source.localeCompare(b.source);
        return a.target.localeCompare(b.target);
      });

    if (!filtered.length) continue;
    const heading = t("relations_owner", { name: cleanInlineText(char.name) });
    const lines = filtered.map((edge) => {
      let line = t("relations_edge", {
        source: cleanInlineText(edge.source),
        target: cleanInlineText(edge.target),
        content: cleanInlineText(edge.content),
      });
      if (edge.temperature) {
        line += t("relations_temperature", { temperature: edge.temperature });
      }
      return line;
    });
    blocks.push(`${heading}\n${lines.join("\n")}`);
  }

  if (!blocks.length) return "";
  return `${t("relations_header")}${t("relations_description")}\n${blocks.join("\n\n")}\n\n`;
}

export function buildStandaloneEffectCatalogBlock(
  effects: Effect[],
  selectedNames?: string[] | string,
  uiLanguage?: string,
): string {
  const rawList = Array.isArray(selectedNames)
    ? selectedNames
    : typeof selectedNames === "string"
      ? selectedNames.split(",")
      : [];
  const selectedKeys = new Set(
    rawList
      .map((s) =>
        String(s ?? "")
          .trim()
          .toLowerCase(),
      )
      .filter(Boolean),
  );
  if (!selectedKeys.size || !effects.length) {
    return "";
  }

  const t = createStandaloneTemplateTranslator(uiLanguage);
  const catalog = new Map<string, { label: string; kind: "audio" | "image" | "image_audio" }>();
  const labelOrder: string[] = [];

  for (const effect of effects) {
    const effectName = String(effect.name ?? "").trim();
    if (!effectName || !selectedKeys.has(effectName.toLowerCase())) continue;

    const audioList = effect.audio_list ?? [];
    const audioTags = tagContents(effect.audio_tags ?? "", audioList.length, true);
    for (let i = 0; i < audioList.length; i += 1) {
      if (!audioList[i] || !audioTags[i]?.trim()) continue;
      for (const rawPart of audioTags[i].split(/[,，]/)) {
        const kw = rawPart.trim();
        if (!kw) continue;
        const key = kw.toLowerCase();
        if (!catalog.has(key)) labelOrder.push(key);
        catalog.set(key, { label: catalog.get(key)?.label ?? kw, kind: "audio" });
      }
    }

    const imageList = effect.image_list ?? [];
    const imageAudio = effect.image_audio_list ?? [];
    const imageTags = tagContents(effect.image_tags ?? "", imageList.length, true);
    for (let i = 0; i < imageList.length; i += 1) {
      if (!imageList[i] || !imageTags[i]?.trim()) continue;
      const hasBoundAudio = Boolean(imageAudio[i]?.trim());
      for (const rawPart of imageTags[i].split(/[,，]/)) {
        const kw = rawPart.trim();
        if (!kw) continue;
        const key = kw.toLowerCase();
        if (!catalog.has(key)) labelOrder.push(key);
        catalog.set(key, {
          label: catalog.get(key)?.label ?? kw,
          kind: hasBoundAudio ? "image_audio" : "image",
        });
      }
    }
  }

  if (!labelOrder.length) return "";

  const lines = [t("effects_header").trim()];
  for (const key of labelOrder) {
    const entry = catalog.get(key);
    if (!entry) continue;
    const hasImage = entry.kind === "image" || entry.kind === "image_audio";
    const modes = hasImage ? "before, after" : "before, after, loop, stop";
    const kindLabel = t(`effect_type_${entry.kind}`);
    lines.push(`- ${entry.label} [${kindLabel}; ${modes}]`);
  }
  return `\n${lines.join("\n")}`;
}
