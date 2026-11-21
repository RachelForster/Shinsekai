import { beforeEach, describe, expect, it } from "vitest";

import type { Character } from "../../../../shared/platform/slices/characterTypes";
import { exportCharPackage, importCharPackage } from "../../../../shared/platform/standalone/packages/charPackageCodec";
import { clearAllStandaloneStorage } from "../../../../shared/platform/standalone/storage/indexedDbStore";
import {
  getVfsBlob,
  putVfsBlob,
  resetVfsRegistryForTests,
  resolveVfsUrl,
} from "../../../../shared/platform/standalone/storage/vfsBlobRegistry";

describe("charPackageCodec", () => {
  beforeEach(async () => {
    resetVfsRegistryForTests();
    await clearAllStandaloneStorage();
  });

  it("round-trips a .char archive with sprites, mouth-sync manifests, refer_audio and conflict handling", async () => {
    const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]);
    const wavBytes = new Uint8Array([0x52, 0x49, 0x46, 0x46, 24, 0, 0, 0, 0x57, 0x41, 0x56, 0x45]);

    const spritePath = "vfs://characters/hoshina/sprites/smile.png";
    const referPath = "vfs://characters/hoshina/models/ref.wav";
    const mouthManifestPath = "vfs://characters/hoshina/mouth-sync/smile/manifest.json";

    await putVfsBlob(spritePath, pngBytes, { mimeType: "image/png" });
    await putVfsBlob("vfs://characters/hoshina/mouth-sync/smile/closed.png", pngBytes, { mimeType: "image/png" });
    await putVfsBlob("vfs://characters/hoshina/mouth-sync/smile/half.png", pngBytes, { mimeType: "image/png" });
    await putVfsBlob("vfs://characters/hoshina/mouth-sync/smile/open.png", pngBytes, { mimeType: "image/png" });
    await putVfsBlob(
      mouthManifestPath,
      new TextEncoder().encode(
        JSON.stringify({
          version: 1,
          width: 128,
          height: 128,
          fps: 24,
          duration: 1,
          patchBox: [0, 0, 32, 32],
          mouths: { closed: "closed.png", half: "half.png", open: "open.png" },
          track: [],
          correction: { offsetX: 0, offsetY: 0, scale: 1, rotation: 0, gain: 1 },
        }),
      ),
      { mimeType: "application/json" },
    );
    await putVfsBlob(referPath, wavBytes, { mimeType: "audio/wav" });

    const original: Character = {
      name: "星奈",
      color: "#7dd3fc",
      sprite_prefix: "hoshina",
      sprites: [{ path: spritePath, group: "常服", mouth_sync: mouthManifestPath }],
      sprite_groups: ["常服"],
      default_sprite_group: "常服",
      fallback_to_default_group: true,
      sprite_scale: 1,
      emotion_tags: "立绘 1：微笑\n",
      avatar_type: "static",
      avatars: {},
      character_brief: "测试向导",
      character_setting: "第一行设定\n第二行说话习惯",
      relation_graph: { nodes: [{ key: "星奈" }], edges: [] },
      refer_audio_path: referPath,
      prompt_text: "你好呀",
      prompt_lang: "zh",
      speech_speed: 1,
      speech_volume: 1,
      pronunciation_map: {},
    };

    const { filename, blob } = await exportCharPackage(original, { triggerDownload: false });
    expect(filename).toBe("星奈.char");
    expect(blob.size).toBeGreaterThan(100);

    // Clear registry before re-importing into clean runtime colliding with existing "星奈"
    resetVfsRegistryForTests();
    const imported = await importCharPackage(blob, [original]);
    expect(imported).toHaveLength(1);

    const dup = imported[0];
    expect(dup.name).toBe("星奈（1）");
    expect(dup.sprite_prefix).toBe("hoshina1");
    expect(dup.character_setting).toContain("第一行设定");
    expect(dup.character_setting).toContain("第二行说话习惯");
    expect(dup.refer_audio_path).toMatch(/^vfs:\/\/characters\/hoshina1\/models\/ref\.wav$/);
    expect(getVfsBlob(dup.refer_audio_path!)).toBeDefined();

    const importedSprite = dup.sprites[0];
    expect(resolveVfsUrl(importedSprite.path)).toMatch(/^blob:/);
    expect(importedSprite.mouth_sync).toMatch(/^vfs:\/\/characters\/hoshina1\/mouth-sync\//);

    const hydratedManifestBlob = getVfsBlob(importedSprite.mouth_sync!);
    expect(hydratedManifestBlob).toBeDefined();
    const manifestJsonText = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.onerror = () => reject(reader.error ?? new Error("read failed"));
      reader.readAsText(hydratedManifestBlob!);
    });
    const hydratedManifest = JSON.parse(manifestJsonText);
    expect(hydratedManifest.mouths.closed).toMatch(/^blob:/);
    expect(hydratedManifest.mouths.half).toMatch(/^blob:/);
    expect(hydratedManifest.mouths.open).toMatch(/^blob:/);
  });
});
