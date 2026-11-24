import type { SpriteMouthManifest } from "../../../assets/spriteMouth";
import { translateRuntimeMessage } from "../../../i18n/runtimeLanguage";
import { SELF_PERSONA_NAME } from "../../../playerCharacterOptions";
import type { Character, Sprite, SpriteTransition } from "../../slices/characterTypes";
import {
  getVfsBlobAsync,
  guessMimeTypeFromPath,
  isVfsPath,
  putVfsBlob,
  resolveVfsUrl,
} from "../storage/vfsBlobRegistry";
import { parseYaml, stringifyCharacterYaml } from "./characterYamlCodec";
import { unzipEntries, zipEntries } from "./zipCodec";

const DEFAULT_CHARACTER_COLOR = "#5b8def";
const RESERVED_CHARACTER_PACKAGE_KEYS = new Set([
  "id",
  "display_name",
  "is_builtin",
  "pinned",
  "undeletable",
  "__proto__",
  "constructor",
  "prototype",
]);
const textDecoder = new TextDecoder("utf-8", { fatal: false });
const textEncoder = new TextEncoder();

function passthroughCharacterFields(source: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (RESERVED_CHARACTER_PACKAGE_KEYS.has(key) || value === undefined) continue;
    result[key] = value;
  }
  return result;
}

function baseName(pathOrUrl: string): string {
  const clean = pathOrUrl.replace(/\\/g, "/").split("?")[0].split("#")[0];
  return clean.split("/").filter(Boolean).pop() ?? "";
}

function parentDir(path: string): string {
  const clean = path.replace(/\\/g, "/");
  const idx = clean.lastIndexOf("/");
  return idx >= 0 ? clean.slice(0, idx) : "";
}

function joinPosix(...parts: string[]): string {
  return parts
    .flatMap((p) => p.replace(/\\/g, "/").split("/"))
    .filter((seg) => seg && seg !== ".")
    .join("/");
}

function resolveNameConflict(rawName: string, existingNames: Set<string>): string {
  const base = rawName.trim() || translateRuntimeMessage("plat.standalone.importedCharDefault");
  if (!existingNames.has(base)) {
    return base;
  }
  let counter = 1;
  let candidate = translateRuntimeMessage("plat.standalone.nameConflictSuffix", { base, count: counter });
  while (existingNames.has(candidate)) {
    counter += 1;
    candidate = translateRuntimeMessage("plat.standalone.nameConflictSuffix", { base, count: counter });
  }
  return candidate;
}

function resolvePrefixConflict(rawPrefix: string, existingPrefixes: Set<string>): string {
  const sanitized = rawPrefix.trim().replace(/[\\/:*?"<>|\s]+/g, "_") || "character";
  if (!existingPrefixes.has(sanitized)) {
    return sanitized;
  }
  let counter = 1;
  let candidate = `${sanitized}${counter}`;
  while (existingPrefixes.has(candidate)) {
    counter += 1;
    candidate = `${sanitized}${counter}`;
  }
  return candidate;
}

async function readBlobBytes(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === "function") {
    return new Uint8Array(await blob.arrayBuffer());
  }
  if (typeof FileReader !== "undefined") {
    return new Promise<Uint8Array>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
      reader.onerror = () => reject(reader.error ?? new Error("Failed to read Blob"));
      reader.readAsArrayBuffer(blob);
    });
  }
  if (typeof Response !== "undefined") {
    return new Uint8Array(await new Response(blob).arrayBuffer());
  }
  throw new Error("Blob reading is unsupported in this environment.");
}

async function readBlobText(blob: Blob): Promise<string> {
  if (typeof blob.text === "function") {
    return blob.text();
  }
  return textDecoder.decode(await readBlobBytes(blob));
}

async function toBytes(source: File | Blob | ArrayBuffer | Uint8Array): Promise<Uint8Array> {
  if (source instanceof Uint8Array) return source;
  if (source instanceof ArrayBuffer) return new Uint8Array(source);
  return readBlobBytes(source);
}

function findEntryBytes(
  entries: Map<string, Uint8Array>,
  candidates: string[],
): { path: string; bytes: Uint8Array } | undefined {
  for (const candidate of candidates) {
    const clean = candidate.replace(/\\/g, "/").replace(/^\.\//, "");
    const exact = entries.get(clean);
    if (exact) return { path: clean, bytes: exact };
    const lower = clean.toLowerCase();
    for (const [k, v] of entries.entries()) {
      if (k.toLowerCase() === lower) {
        return { path: k, bytes: v };
      }
    }
  }
  return undefined;
}

function findEntryByBasenameUnderPrefix(
  entries: Map<string, Uint8Array>,
  folderPrefix: string,
  targetName: string,
): { path: string; bytes: Uint8Array } | undefined {
  const normalizedTarget = baseName(targetName).toLowerCase();
  if (!normalizedTarget) return undefined;
  const normPrefix = folderPrefix.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  for (const [entryPath, bytes] of entries.entries()) {
    const lowerPath = entryPath.toLowerCase();
    if (normPrefix && !lowerPath.startsWith(`${normPrefix}/`)) {
      continue;
    }
    if (baseName(entryPath).toLowerCase() === normalizedTarget) {
      return { path: entryPath, bytes };
    }
  }
  return undefined;
}

function buildPortableMouthManifestPath(prefix: string, mouthSyncRelative: string): string {
  const cleanRel = mouthSyncRelative.replace(/\\/g, "/").replace(/^\.\//, "");
  return `vfs://characters/${prefix}/${cleanRel}.portable.json`;
}

async function storeMouthSyncBundle(
  entries: Map<string, Uint8Array>,
  originalPrefix: string,
  newPrefix: string,
  mouthSyncRel: string,
): Promise<string | null> {
  const cleanRel = mouthSyncRel.replace(/\\/g, "/").replace(/^\.\//, "");
  const sourceManifest = findEntryBytes(entries, [joinPosix("sprites", originalPrefix, cleanRel), cleanRel]);
  if (!sourceManifest) return null;

  let parsedManifest: SpriteMouthManifest;
  try {
    parsedManifest = JSON.parse(textDecoder.decode(sourceManifest.bytes)) as SpriteMouthManifest;
  } catch {
    return null;
  }

  // Persist raw portable manifest so export can reconstruct exact PNG relative paths
  await putVfsBlob(buildPortableMouthManifestPath(newPrefix, cleanRel), sourceManifest.bytes, {
    mimeType: "application/json",
    persist: true,
  });

  const manifestDirInZip = parentDir(sourceManifest.path);
  const resolvedMouths = { ...parsedManifest.mouths };

  for (const pose of ["closed", "half", "open"] as const) {
    const rawRel = parsedManifest.mouths?.[pose];
    if (!rawRel) continue;
    const targetZipPath = joinPosix(manifestDirInZip, rawRel);
    const pngEntry = findEntryBytes(entries, [targetZipPath, joinPosix("sprites", originalPrefix, rawRel)]);
    if (!pngEntry) continue;

    const mouthDirRel = parentDir(cleanRel);
    const vfsPngPath = `vfs://characters/${newPrefix}/${joinPosix(mouthDirRel, rawRel)}`;
    const blobUrl = await putVfsBlob(vfsPngPath, pngEntry.bytes, {
      mimeType: guessMimeTypeFromPath(vfsPngPath, "image/png"),
      persist: true,
    });
    resolvedMouths[pose] = blobUrl;
  }

  const hydratedManifest: SpriteMouthManifest = {
    ...parsedManifest,
    mouths: resolvedMouths,
  };
  const vfsManifestPath = `vfs://characters/${newPrefix}/${cleanRel}`;
  await putVfsBlob(vfsManifestPath, textEncoder.encode(JSON.stringify(hydratedManifest)), {
    mimeType: "application/json",
    persist: true,
  });

  return vfsManifestPath;
}

/**
 * Refreshes `blob:` ObjectURLs inside stored mouth-sync manifests on startup after
 * `hydrateVfsBlobs()`, because `blob:` URLs expire across browser page reloads.
 */
export async function refreshCharacterMouthManifestUrls(characters: Character[]): Promise<void> {
  for (const char of characters) {
    for (const sprite of char.sprites ?? []) {
      const mouthPath = sprite.mouth_sync;
      if (!mouthPath || !isVfsPath(mouthPath)) continue;

      const manifestBlob = await getVfsBlobAsync(mouthPath);
      if (!manifestBlob) continue;
      let parsed: SpriteMouthManifest;
      try {
        parsed = JSON.parse(await readBlobText(manifestBlob)) as SpriteMouthManifest;
      } catch {
        continue;
      }

      const portableBlob = await getVfsBlobAsync(`${mouthPath}.portable.json`);
      let portableMouths: Partial<Record<"closed" | "half" | "open", string>> = {};
      if (portableBlob) {
        try {
          const rawPortable = JSON.parse(await readBlobText(portableBlob)) as SpriteMouthManifest;
          portableMouths = rawPortable.mouths ?? {};
        } catch {
          // Ignore malformed portable manifest
        }
      }

      const manifestDir = parentDir(mouthPath);
      const nextMouths = { ...parsed.mouths };
      let changed = false;

      for (const pose of ["closed", "half", "open"] as const) {
        const relName = portableMouths[pose] || parsed.mouths?.[pose];
        if (!relName) continue;
        if (relName.startsWith("vfs://")) {
          const url = resolveVfsUrl(relName);
          if (url && url !== nextMouths[pose]) {
            nextMouths[pose] = url;
            changed = true;
          }
          continue;
        }
        if (!relName.startsWith("blob:") && !relName.startsWith("data:") && !relName.startsWith("http")) {
          const vfsPngPath = `${manifestDir}/${relName}`;
          const url = resolveVfsUrl(vfsPngPath);
          if (url.startsWith("blob:")) {
            nextMouths[pose] = url;
            changed = true;
          }
        }
      }

      if (changed) {
        await putVfsBlob(mouthPath, textEncoder.encode(JSON.stringify({ ...parsed, mouths: nextMouths })), {
          mimeType: "application/json",
          persist: true,
        });
      }
    }
  }
}

function normalizeRelationGraph(rawGraph: unknown, oldName: string, newName: string) {
  if (!rawGraph || typeof rawGraph !== "object") {
    return { nodes: [], edges: [] };
  }
  const graph = rawGraph as {
    nodes?: Array<{ key?: string }>;
    edges?: Array<{ source?: string; target?: string; temperature?: number; content?: string }>;
  };
  const nodes = Array.isArray(graph.nodes)
    ? graph.nodes
        .filter((n) => typeof n?.key === "string" && n.key.trim())
        .map((n) => ({
          key: oldName !== newName && n.key === oldName ? newName : String(n.key),
        }))
    : [];
  const edges = Array.isArray(graph.edges)
    ? graph.edges
        .filter((e) => typeof e?.source === "string" && typeof e?.target === "string")
        .map((e) => ({
          source: oldName !== newName && e.source === oldName ? newName : String(e.source),
          target: oldName !== newName && e.target === oldName ? newName : String(e.target),
          temperature: typeof e.temperature === "number" ? e.temperature : 0,
          content: typeof e.content === "string" ? e.content : "",
        }))
    : [];
  return { nodes, edges };
}

export async function importCharPackage(
  source: File | Blob | ArrayBuffer | Uint8Array,
  existingCharacters: Character[],
): Promise<Character[]> {
  const bytes = await toBytes(source);
  const entries = await unzipEntries(bytes);

  const yamlEntry =
    findEntryBytes(entries, ["character.yaml", "characters.yaml", "character.yml"]) ??
    findEntryBytes(entries, ["character.json"]);
  if (!yamlEntry) {
    throw new Error(translateRuntimeMessage("plat.standalone.charYamlMissing"));
  }

  const parsed = parseYaml(textDecoder.decode(yamlEntry.bytes));
  const rawList = Array.isArray(parsed)
    ? parsed
    : parsed && typeof parsed === "object" && Array.isArray((parsed as { characters?: unknown[] }).characters)
      ? (parsed as { characters: unknown[] }).characters
      : parsed && typeof parsed === "object"
        ? [parsed]
        : [];

  if (!rawList.length || !rawList.every((item) => item && typeof item === "object")) {
    throw new Error(translateRuntimeMessage("plat.standalone.charYamlInvalid"));
  }

  const existingNames = new Set<string>([SELF_PERSONA_NAME, ...existingCharacters.map((c) => c.name)]);
  const existingPrefixes = new Set<string>(["user_self", ...existingCharacters.map((c) => c.sprite_prefix)]);

  const imported: Character[] = [];

  for (const rawItem of rawList) {
    const raw = rawItem as Record<string, unknown>;
    const defaultNewCharName = translateRuntimeMessage("plat.standalone.newCharDefault");
    const originalName = String(raw.name ?? defaultNewCharName).trim() || defaultNewCharName;
    const originalPrefix = String(raw.sprite_prefix ?? originalName).trim() || "char";

    const newName = resolveNameConflict(originalName, existingNames);
    const newPrefix = resolvePrefixConflict(originalPrefix, existingPrefixes);
    existingNames.add(newName);
    existingPrefixes.add(newPrefix);

    const spritesRaw = Array.isArray(raw.sprites) ? raw.sprites : [];
    const nextSprites: Sprite[] = [];
    const spriteBasenameToVfs = new Map<string, string>();

    for (const sItem of spritesRaw) {
      if (!sItem || typeof sItem !== "object") continue;
      const sObj = sItem as Record<string, unknown>;
      const origSpritePath = String(sObj.path ?? "").trim();
      let vfsSpritePath = "";

      if (origSpritePath) {
        const spriteName = baseName(origSpritePath);
        const found =
          findEntryBytes(entries, [
            joinPosix("sprites", originalPrefix, spriteName),
            joinPosix("sprites", originalPrefix, origSpritePath),
            origSpritePath,
          ]) ?? findEntryByBasenameUnderPrefix(entries, "sprites", spriteName);

        if (found) {
          vfsSpritePath = `vfs://characters/${newPrefix}/sprites/${spriteName}`;
          await putVfsBlob(vfsSpritePath, found.bytes, {
            mimeType: guessMimeTypeFromPath(spriteName),
            persist: true,
          });
          spriteBasenameToVfs.set(spriteName.toLowerCase(), vfsSpritePath);
        }
      }

      let vfsVoicePath = "";
      const origVoicePath = String(sObj.voice_path ?? "").trim();
      if (origVoicePath) {
        const voiceName = baseName(origVoicePath);
        const foundVoice =
          findEntryBytes(entries, [
            joinPosix("speech", originalPrefix, voiceName),
            joinPosix("sprites", originalPrefix, voiceName),
            origVoicePath,
          ]) ?? findEntryByBasenameUnderPrefix(entries, "speech", voiceName);
        if (foundVoice) {
          vfsVoicePath = `vfs://characters/${newPrefix}/speech/${voiceName}`;
          await putVfsBlob(vfsVoicePath, foundVoice.bytes, {
            mimeType: guessMimeTypeFromPath(voiceName, "audio/wav"),
            persist: true,
          });
        }
      }

      let vfsMouthPath: string | null = null;
      const origMouthSync = typeof sObj.mouth_sync === "string" ? sObj.mouth_sync.trim() : "";
      if (origMouthSync) {
        vfsMouthPath = await storeMouthSyncBundle(entries, originalPrefix, newPrefix, origMouthSync);
      }

      const crop =
        sObj.portrait_crop && typeof sObj.portrait_crop === "object"
          ? (sObj.portrait_crop as Sprite["portrait_crop"])
          : undefined;

      nextSprites.push({
        path: vfsSpritePath || origSpritePath,
        ...(typeof sObj.group === "string" && sObj.group ? { group: sObj.group } : {}),
        ...(vfsMouthPath ? { mouth_sync: vfsMouthPath } : {}),
        ...(crop !== undefined ? { portrait_crop: crop } : {}),
        ...(vfsVoicePath ? { voice_path: vfsVoicePath } : {}),
        ...(typeof sObj.voice_text === "string" ? { voice_text: sObj.voice_text } : {}),
        ...(typeof sObj.voice_type === "string" ? { voice_type: sObj.voice_type as Sprite["voice_type"] } : {}),
      });
    }

    // Store sprite transitions
    const nextTransitions: SpriteTransition[] = [];
    const transitionsRaw = Array.isArray(raw.sprite_transitions) ? raw.sprite_transitions : [];
    for (const trItem of transitionsRaw) {
      if (!trItem || typeof trItem !== "object") continue;
      const tr = trItem as Record<string, unknown>;
      const relClip = String(tr.path ?? "").trim();
      if (!relClip) continue;
      const clipName = baseName(relClip);
      const foundClip =
        findEntryBytes(entries, [
          joinPosix("sprites", originalPrefix, relClip),
          joinPosix("sprites", originalPrefix, "transitions", clipName),
          relClip,
        ]) ?? findEntryByBasenameUnderPrefix(entries, "sprites", clipName);
      if (!foundClip) continue;

      const vfsClipPath = `vfs://characters/${newPrefix}/transitions/${clipName}`;
      await putVfsBlob(vfsClipPath, foundClip.bytes, {
        mimeType: guessMimeTypeFromPath(clipName, "video/webm"),
        persist: true,
      });

      const fromKey = baseName(String(tr.from_path ?? "")).toLowerCase();
      const toKey = baseName(String(tr.to_path ?? "")).toLowerCase();
      nextTransitions.push({
        frame_count: typeof tr.frame_count === "number" ? tr.frame_count : undefined,
        h3_resolution:
          typeof tr.h3_resolution === "string" ? (tr.h3_resolution as SpriteTransition["h3_resolution"]) : undefined,
        from_path: spriteBasenameToVfs.get(fromKey) ?? String(tr.from_path ?? ""),
        to_path: spriteBasenameToVfs.get(toKey) ?? String(tr.to_path ?? ""),
        path: vfsClipPath,
        from_fingerprint: String(tr.from_fingerprint ?? ""),
        to_fingerprint: String(tr.to_fingerprint ?? ""),
      });
    }

    // Reference audio for cloud zero-shot TTS cloning
    let vfsReferAudio = "";
    const origReferAudio = typeof raw.refer_audio_path === "string" ? raw.refer_audio_path.trim() : "";
    if (origReferAudio) {
      const refName = baseName(origReferAudio);
      const foundRef =
        findEntryBytes(entries, [
          origReferAudio.replace(/\\/g, "/"),
          joinPosix("models", refName),
          joinPosix("speech", originalPrefix, refName),
        ]) ?? findEntryByBasenameUnderPrefix(entries, "models", refName);
      if (foundRef) {
        vfsReferAudio = `vfs://characters/${newPrefix}/models/${refName}`;
        await putVfsBlob(vfsReferAudio, foundRef.bytes, {
          mimeType: guessMimeTypeFromPath(refName, "audio/wav"),
          persist: true,
        });
      }
    }

    const character: Character = {
      ...(passthroughCharacterFields(raw) as Partial<Character>),
      name: newName,
      color: String(raw.color ?? DEFAULT_CHARACTER_COLOR).trim() || DEFAULT_CHARACTER_COLOR,
      sprite_prefix: newPrefix,
      portrait_sprite_index: typeof raw.portrait_sprite_index === "number" ? raw.portrait_sprite_index : 0,
      sprites: nextSprites,
      sprite_scale: typeof raw.sprite_scale === "number" ? raw.sprite_scale : 1,
      emotion_tags: String(raw.emotion_tags ?? ""),
      avatar_type: String(raw.avatar_type ?? "static") || "static",
      avatars: (raw.avatars && typeof raw.avatars === "object" ? raw.avatars : {}) as Character["avatars"],
      character_brief: String(raw.character_brief ?? ""),
      character_setting: String(raw.character_setting ?? ""),
      relation_graph: normalizeRelationGraph(raw.relation_graph, originalName, newName),
      sprite_groups: Array.isArray(raw.sprite_groups) ? raw.sprite_groups.map((g) => String(g)) : [],
      default_sprite_group: typeof raw.default_sprite_group === "string" ? raw.default_sprite_group : "",
      fallback_to_default_group:
        raw.fallback_to_default_group !== undefined ? Boolean(raw.fallback_to_default_group) : true,
      ...(raw.portrait_crop && typeof raw.portrait_crop === "object"
        ? { portrait_crop: raw.portrait_crop as Character["portrait_crop"] }
        : {}),
      ...(nextTransitions.length ? { sprite_transitions: nextTransitions } : {}),
      gpt_model_path: "",
      sovits_model_path: "",
      refer_audio_path: vfsReferAudio,
      prompt_text: String(raw.prompt_text ?? ""),
      prompt_lang: String(raw.prompt_lang ?? ""),
      speech_speed: typeof raw.speech_speed === "number" ? raw.speech_speed : 1,
      speech_volume: typeof raw.speech_volume === "number" ? raw.speech_volume : 1,
      pronunciation_map:
        raw.pronunciation_map && typeof raw.pronunciation_map === "object"
          ? (raw.pronunciation_map as Record<string, string>)
          : {},
    };

    imported.push(character);
  }

  return imported;
}

async function readAssetBytes(pathOrUrl: string): Promise<Uint8Array | null> {
  if (!pathOrUrl) return null;
  if (isVfsPath(pathOrUrl)) {
    const blob = await getVfsBlobAsync(pathOrUrl);
    if (!blob) return null;
    return readBlobBytes(blob);
  }
  const resolved = resolveVfsUrl(pathOrUrl);
  if (typeof fetch !== "undefined" && resolved) {
    try {
      const resp = await fetch(resolved);
      if (resp.ok) {
        return new Uint8Array(await resp.arrayBuffer());
      }
    } catch {
      return null;
    }
  }
  return null;
}

export async function exportCharPackage(
  character: Character,
  options?: { triggerDownload?: boolean },
): Promise<{ filename: string; blob: Blob }> {
  const archiveEntries: Record<string, Uint8Array> = {};
  const prefix = character.sprite_prefix || "character";
  const exportedSprites: Array<Record<string, unknown>> = [];

  for (let i = 0; i < (character.sprites ?? []).length; i += 1) {
    const sprite = character.sprites[i];
    const spriteName = baseName(sprite.path) || `sprite_${i + 1}.png`;
    const spriteBytes = await readAssetBytes(sprite.path);
    if (spriteBytes) {
      archiveEntries[`sprites/${prefix}/${spriteName}`] = spriteBytes;
    }

    let voiceFilename = "";
    if (sprite.voice_path) {
      voiceFilename = baseName(sprite.voice_path) || `voice_${i + 1}.wav`;
      const voiceBytes = await readAssetBytes(sprite.voice_path);
      if (voiceBytes) {
        archiveEntries[`speech/${prefix}/${voiceFilename}`] = voiceBytes;
      }
    }

    let mouthRel = "";
    if (sprite.mouth_sync && isVfsPath(sprite.mouth_sync)) {
      const portableBlob = await getVfsBlobAsync(`${sprite.mouth_sync}.portable.json`);
      const activeBlob = portableBlob ?? (await getVfsBlobAsync(sprite.mouth_sync));
      if (activeBlob) {
        const mouthFolder = `mouth-sync/sprite_${i + 1}`;
        mouthRel = `${mouthFolder}/manifest.json`;
        const manifestBytes = await readBlobBytes(activeBlob);
        archiveEntries[`sprites/${prefix}/${mouthRel}`] = manifestBytes;

        try {
          const parsedManifest = JSON.parse(textDecoder.decode(manifestBytes)) as SpriteMouthManifest;
          const vfsManifestDir = parentDir(sprite.mouth_sync);
          for (const pose of ["closed", "half", "open"] as const) {
            const relImg = parsedManifest.mouths?.[pose];
            if (!relImg || relImg.startsWith("blob:")) continue;
            const pngBytes = await readAssetBytes(`${vfsManifestDir}/${relImg}`);
            if (pngBytes) {
              archiveEntries[`sprites/${prefix}/${mouthFolder}/${relImg}`] = pngBytes;
            }
          }
        } catch {
          // Ignore malformed mouth manifest during export
        }
      }
    }

    const spriteObj: Record<string, unknown> = {
      path: spriteName,
    };
    if (sprite.group) spriteObj.group = sprite.group;
    if (sprite.portrait_crop !== undefined) spriteObj.portrait_crop = sprite.portrait_crop;
    if (voiceFilename) spriteObj.voice_path = voiceFilename;
    if (sprite.voice_text) spriteObj.voice_text = sprite.voice_text;
    if (sprite.voice_type) spriteObj.voice_type = sprite.voice_type;
    if (mouthRel) spriteObj.mouth_sync = mouthRel;
    exportedSprites.push(spriteObj);
  }

  const exportedTransitions: Array<Record<string, unknown>> = [];
  for (let i = 0; i < (character.sprite_transitions ?? []).length; i += 1) {
    const tr = character.sprite_transitions![i];
    const clipName = baseName(tr.path) || `transition_${i + 1}.webm`;
    const clipBytes = await readAssetBytes(tr.path);
    if (!clipBytes) continue;
    archiveEntries[`sprites/${prefix}/transitions/${clipName}`] = clipBytes;
    exportedTransitions.push({
      ...(tr.frame_count !== undefined ? { frame_count: tr.frame_count } : {}),
      ...(tr.h3_resolution ? { h3_resolution: tr.h3_resolution } : {}),
      from_path: baseName(tr.from_path),
      to_path: baseName(tr.to_path),
      path: `transitions/${clipName}`,
      from_fingerprint: tr.from_fingerprint,
      to_fingerprint: tr.to_fingerprint,
    });
  }

  let exportedReferAudio: string | null = null;
  if (character.refer_audio_path) {
    const refName = baseName(character.refer_audio_path) || "refer_audio.wav";
    const refBytes = await readAssetBytes(character.refer_audio_path);
    if (refBytes) {
      exportedReferAudio = `models/${refName}`;
      archiveEntries[exportedReferAudio] = refBytes;
    }
  }

  const yamlObj: Record<string, unknown> = {
    ...passthroughCharacterFields(character as unknown as Record<string, unknown>),
    name: character.name,
    color: character.color || DEFAULT_CHARACTER_COLOR,
    sprite_prefix: prefix,
    prompt_text: character.prompt_text ?? "",
    prompt_lang: character.prompt_lang ?? "",
    sprite_scale: character.sprite_scale ?? 1,
    portrait_sprite_index: character.portrait_sprite_index ?? 0,
    portrait_crop: character.portrait_crop ?? null,
    sprites: exportedSprites,
    emotion_tags: character.emotion_tags ?? "",
    sprite_groups: character.sprite_groups ?? [],
    default_sprite_group: character.default_sprite_group ?? "",
    fallback_to_default_group: character.fallback_to_default_group ?? true,
    avatar_type: character.avatar_type || "static",
    avatars: {},
    sprite_transitions: exportedTransitions,
    character_brief: character.character_brief ?? "",
    relation_graph: character.relation_graph ?? { nodes: [], edges: [] },
    character_setting: character.character_setting ?? "",
    speech_speed: character.speech_speed ?? 1,
    speech_volume: character.speech_volume ?? 1,
    pronunciation_map: character.pronunciation_map ?? {},
    gpt_model_path: null,
    sovits_model_path: null,
    refer_audio_path: exportedReferAudio,
  };

  archiveEntries["character.yaml"] = textEncoder.encode(stringifyCharacterYaml([yamlObj]));
  archiveEntries["manifest.json"] = textEncoder.encode(
    JSON.stringify({ exportedAt: new Date().toISOString(), original_paths: {} }, null, 2),
  );

  const zipBytes = await zipEntries(archiveEntries);
  const safeCopy = new Uint8Array(zipBytes.byteLength);
  safeCopy.set(zipBytes);
  const blob = new Blob([safeCopy], { type: "application/zip" });
  const safeFileBase = character.name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "character";
  const filename = `${safeFileBase}.char`;

  if (options?.triggerDownload !== false && typeof document !== "undefined") {
    try {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.setTimeout(() => {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // Ignore revoke failure
        }
      }, 2000);
    } catch {
      // Non-DOM or blocked download fallback handled by caller
    }
  }

  return { filename, blob };
}
