import { describe, expect, it } from "vitest";

import { attachmentNameFromPath, mergeChatAttachmentInputs } from "../../../features/chat-stage/attachments";

describe("chat attachment path labels", () => {
  it("extracts Windows and portable path leaf names", () => {
    expect(attachmentNameFromPath(String.raw`C:\Users\Mio\voice.wav`)).toBe("voice.wav");
    expect(attachmentNameFromPath("data/chat_attachments/voice.wav")).toBe("voice.wav");
  });

  it("preserves a literal backslash in a POSIX filename", () => {
    expect(attachmentNameFromPath(String.raw`/tmp/uploads/voice\alternate.wav`)).toBe(String.raw`voice\alternate.wav`);
  });

  it("deduplicates alternate Windows separators without collapsing POSIX names", () => {
    const windows = mergeChatAttachmentInputs(
      [{ kind: "image", name: "first", path: String.raw`C:\Users\Mio\scene.png` }],
      [{ kind: "image", name: "second", path: "C:/Users/Mio/scene.png" }],
    );
    expect(windows).toHaveLength(1);

    const posix = mergeChatAttachmentInputs(
      [{ kind: "image", name: "literal", path: String.raw`/tmp/scene\alternate.png` }],
      [{ kind: "image", name: "nested", path: "/tmp/scene/alternate.png" }],
    );
    expect(posix).toHaveLength(2);
  });
});
