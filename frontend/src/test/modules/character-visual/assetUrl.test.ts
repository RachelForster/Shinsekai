import { describe, expect, it } from "vitest";
import { avatarAssetUrl, avatarRuntimeAssetUrl } from "../../../modules/character-visual/assetUrl";

describe("avatarAssetUrl", () => {
  it("serves installed runtimes from the model bridge origin, retaining desktop/mobile authentication", () => {
    const url = new URL(
      avatarRuntimeAssetUrl(
        "http://127.0.0.1:8787/api/avatar/file?model_path=C%3A%2Fmodel.json&path=model.json&shinsekai_bridge_token=a%2Bb",
        "l2d",
        "cubism-sdk.js",
      ),
    );
    expect(url.origin).toBe("http://127.0.0.1:8787");
    expect(url.pathname).toBe("/api/avatar/runtime/file");
    expect(url.searchParams.get("model_path")).toBeNull();
    expect(url.searchParams.get("format")).toBe("l2d");
    expect(url.searchParams.get("path")).toBe("cubism-sdk.js");
    expect(url.searchParams.get("shinsekai_bridge_token")).toBe("a+b");
  });
  it.each(["../sdk.js", "https://other/sdk.js", "%2e%2e/sdk.js", "sdk.js?path=secret"])(
    "rejects unsafe runtime resources: %s",
    (file) => {
      expect(() => avatarRuntimeAssetUrl("http://localhost/model.json", "l2d", file)).toThrow();
    },
  );
  it("retains bridge authentication while resolving a model dependency", () => {
    const url = new URL(
      avatarAssetUrl(
        "http://localhost/api/media?path=C%3A%5Cmodels%5Calice%5Cmodel.json&shinsekai_bridge_token=test",
        "textures/face.png",
      ),
    );
    expect(url.pathname).toBe("/api/media");
    expect(url.searchParams.get("path")).toBe("C:/models/alice/textures/face.png");
    expect(url.searchParams.get("shinsekai_bridge_token")).toBe("test");
  });
  it("resolves dependencies against the model directory", () => {
    expect(avatarAssetUrl("http://localhost/assets/alice/model.json", "textures/face 1.png")).toBe(
      "http://localhost/assets/alice/textures/face%201.png",
    );
  });
  it.each([
    "../secret",
    "%2e%2e/secret",
    "..\\secret",
    "https://other/face.png",
    "/face.png",
    "//other/face.png",
    "face.png?path=secret",
  ])("rejects out-of-package references: %s", (path) => {
    expect(() => avatarAssetUrl("http://localhost/assets/alice/model.json", path)).toThrow();
  });
});
