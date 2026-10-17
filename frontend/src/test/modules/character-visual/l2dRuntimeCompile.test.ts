// @vitest-environment node
import { describe, expect, it } from "vitest";
import { compileRuntime } from "../../../modules/character-visual/adapters/l2d/compileRuntime";

describe("offline Cubism compiler", () => {
  it("rejects invalid or incomplete SDK input before execution", async () => {
    const signal = new AbortController().signal;
    await expect(compileRuntime(null, signal)).rejects.toThrow("Invalid SDK sources");
    await expect(compileRuntime({ sources: {} }, signal)).rejects.toThrow("Missing SDK dependency");
  });

  it("honours cancellation before compilation", async () => {
    const abort = new AbortController();
    abort.abort();
    await expect(compileRuntime({}, abort.signal)).rejects.toMatchObject({ name: "AbortError" });
  });
});
