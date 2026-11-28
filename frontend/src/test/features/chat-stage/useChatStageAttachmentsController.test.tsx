import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  uploadChatAttachments: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  uploadChatAttachments: (...args: unknown[]) => mocks.uploadChatAttachments(...args),
}));

import { CHAT_ATTACHMENT_LIMIT } from "../../../features/chat-stage/attachments";
import { useChatStageAttachmentsController } from "../../../features/chat-stage/controllers/useChatStageAttachmentsController";
import type { ChatAttachmentInput } from "../../../shared/platform/types";

describe("useChatStageAttachmentsController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uploads accepted dropped files up to limit, tracks pending uploads synchronously, and reports overflow", async () => {
    let resolveUpload!: (value: { attachments: ChatAttachmentInput[] }) => void;
    mocks.uploadChatAttachments.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpload = resolve;
        }),
    );
    const dispatch = vi.fn();
    const showToast = vi.fn();
    const existing: ChatAttachmentInput[] = Array.from({ length: CHAT_ATTACHMENT_LIMIT - 1 }, (_, index) => ({
      kind: "image",
      name: `existing-${index}.png`,
      path: `/tmp/existing-${index}.png`,
    }));

    const { result } = renderHook(() =>
      useChatStageAttachmentsController({
        dispatch,
        inputAttachments: existing,
        showToast,
        t: (key) => key,
      }),
    );

    const file1 = new File(["a"], "one.png", { type: "image/png" });
    const file2 = new File(["b"], "two.png", { type: "image/png" });

    let dropPromise!: Promise<void>;
    act(() => {
      dropPromise = result.current.handleDropFiles([file1, file2]);
    });

    expect(result.current.hasPendingUploads()).toBe(true);
    expect(result.current.attachmentUploadPending).toBe(true);
    expect(mocks.uploadChatAttachments).toHaveBeenCalledWith([file1]);
    expect(showToast).toHaveBeenCalledWith({
      kind: "error",
      message: "chat.input.attachmentLimit",
      title: "common.operationFailed",
    });

    const uploaded: ChatAttachmentInput[] = [{ kind: "image", name: "one.png", path: "/tmp/one.png" }];
    await act(async () => {
      resolveUpload({ attachments: uploaded });
      await dropPromise;
    });

    expect(result.current.hasPendingUploads()).toBe(false);
    expect(result.current.attachmentUploadPending).toBe(false);
    expect(dispatch).toHaveBeenCalledWith({ attachments: uploaded, type: "addAttachments" });
  });

  it("resets pending state and shows an error toast when upload fails", async () => {
    mocks.uploadChatAttachments.mockRejectedValue(new Error("upload crashed"));
    const dispatch = vi.fn();
    const showToast = vi.fn();

    const { result } = renderHook(() =>
      useChatStageAttachmentsController({
        dispatch,
        inputAttachments: [],
        showToast,
        t: (key) => key,
      }),
    );

    await act(async () => {
      await result.current.handleDropFiles([new File(["a"], "broken.txt", { type: "text/plain" })]);
    });

    expect(result.current.hasPendingUploads()).toBe(false);
    expect(result.current.attachmentUploadPending).toBe(false);
    expect(showToast).toHaveBeenCalledWith({
      kind: "error",
      message: "upload crashed",
      title: "common.operationFailed",
    });
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("clicks the matching picker input, resets picked input value, and removes attachments", async () => {
    const uploaded: ChatAttachmentInput[] = [{ kind: "file", name: "doc.txt", path: "/tmp/doc.txt" }];
    mocks.uploadChatAttachments.mockResolvedValue({ attachments: uploaded });
    const dispatch = vi.fn();
    const showToast = vi.fn();
    const kept: ChatAttachmentInput = { kind: "image", name: "keep.png", path: "/tmp/keep.png" };

    const { result } = renderHook(() =>
      useChatStageAttachmentsController({
        dispatch,
        inputAttachments: [kept, ...uploaded],
        showToast,
        t: (key) => key,
      }),
    );

    const imageClick = vi.fn();
    const fileClick = vi.fn();
    result.current.imageAttachmentInputRef.current = { click: imageClick } as unknown as HTMLInputElement;
    result.current.fileAttachmentInputRef.current = { click: fileClick } as unknown as HTMLInputElement;

    act(() => result.current.pickAttachments("image"));
    act(() => result.current.pickAttachments("file"));
    expect(imageClick).toHaveBeenCalledTimes(1);
    expect(fileClick).toHaveBeenCalledTimes(1);

    const pickedFile = new File(["doc"], "doc.txt", { type: "text/plain" });
    const mockInput = {
      files: [pickedFile] as unknown as FileList,
      value: "C:\\fakepath\\doc.txt",
    } as HTMLInputElement;

    await act(async () => {
      result.current.handlePickedFiles(mockInput);
      await Promise.resolve();
    });
    expect(mockInput.value).toBe("");
    expect(mocks.uploadChatAttachments).toHaveBeenCalledWith([pickedFile]);

    act(() => result.current.removeAttachment(uploaded[0]!));
    expect(dispatch).toHaveBeenCalledWith({
      attachments: [kept],
      type: "setAttachments",
    });
  });
});
