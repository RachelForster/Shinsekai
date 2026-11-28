import type { ChatAttachmentInput } from "../../../shared/platform/types";
import { CHAT_ATTACHMENT_LIMIT } from "../attachments";
import { emptyChatState, type ChatStageState } from "../chatState";

export interface ChatRouteInputState {
  inputAttachments: ChatAttachmentInput[];
  inputDraft: string;
}

export function chatRouteInputState(value: unknown): ChatRouteInputState {
  if (!value || typeof value !== "object") {
    return { inputAttachments: [], inputDraft: "" };
  }
  const chatInput = (value as { chatInput?: unknown }).chatInput;
  if (!chatInput || typeof chatInput !== "object") {
    return { inputAttachments: [], inputDraft: "" };
  }
  const candidate = chatInput as { inputAttachments?: unknown; inputDraft?: unknown };
  const inputAttachments = Array.isArray(candidate.inputAttachments)
    ? candidate.inputAttachments
        .filter((attachment): attachment is ChatAttachmentInput =>
          Boolean(
            attachment &&
            typeof attachment === "object" &&
            ((attachment as ChatAttachmentInput).kind === "file" ||
              (attachment as ChatAttachmentInput).kind === "image") &&
            typeof (attachment as ChatAttachmentInput).name === "string" &&
            typeof (attachment as ChatAttachmentInput).path === "string",
          ),
        )
        .slice(0, CHAT_ATTACHMENT_LIMIT)
        .map((attachment) => ({ ...attachment }))
    : [];
  return {
    inputAttachments,
    inputDraft: typeof candidate.inputDraft === "string" ? candidate.inputDraft : "",
  };
}

export function initialChatStageState(routeState: unknown): ChatStageState {
  return { ...emptyChatState, ...chatRouteInputState(routeState) };
}

export function withChatRouteInputState(routeState: unknown, chatInput: ChatRouteInputState): Record<string, unknown> {
  const previousState =
    routeState && typeof routeState === "object" && !Array.isArray(routeState)
      ? (routeState as Record<string, unknown>)
      : {};
  return {
    ...previousState,
    chatInput: {
      inputAttachments: chatInput.inputAttachments.map((attachment) => ({ ...attachment })),
      inputDraft: chatInput.inputDraft,
    },
  };
}
