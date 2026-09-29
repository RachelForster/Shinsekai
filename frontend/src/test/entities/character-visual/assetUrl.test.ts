import { describe, expect, it } from "vitest";
import { avatarAssetUrl } from "../../../entities/character-visual/assetUrl";

describe("avatarAssetUrl", () => {
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
