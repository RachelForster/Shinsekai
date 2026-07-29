import type { SyntheticEvent } from "react";

import { fileUrl } from "../../entities/files/repository";
import type { MessageKey } from "../../shared/i18n";
import type { ChatTransportMode, ChatTransportState } from "../../shared/platform/types";

interface ChatStagePageLocation {
  hostname: string;
  protocol: string;
}

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "localhost"]);

function isLoopbackHost(hostname: string) {
  return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

export function isRemoteMobileAccessPage(
  location: ChatStagePageLocation | undefined = typeof window !== "undefined" ? window.location : undefined,
) {
  return Boolean(location && /^https?:$/.test(location.protocol) && !isLoopbackHost(location.hostname));
}

export function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function eventTargetElement(target: EventTarget | null) {
  if (target instanceof Element) {
    return target;
  }
  if (target instanceof Node) {
    return target.parentElement;
  }
  return null;
}

export function isChatStageHitbox(target: EventTarget | null) {
  return Boolean(eventTargetElement(target)?.closest("[data-chat-stage-hitbox='true']"));
}

export function isPointInsideChatStageHitbox(x: number, y: number) {
  const hitboxes = document.querySelectorAll<HTMLElement>("[data-chat-stage-hitbox='true']");
  for (const hitbox of hitboxes) {
    if (hitbox.hidden || hitbox.getAttribute("aria-hidden") === "true") {
      continue;
    }
    const rect = hitbox.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      continue;
    }
    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
      return true;
    }
  }
  return false;
}

export function layerClassName(base: string, hidden: boolean) {
  return classNames(base, hidden && "chat-stage__layer--hidden");
}

export function hideBrokenStageAsset(event: SyntheticEvent<HTMLImageElement>) {
  event.currentTarget.dataset.loadState = "error";
}

export function stageAssetUrl(path?: string) {
  if (!path) {
    return "";
  }
  if (/^https?:\/\//i.test(path) && typeof window !== "undefined") {
    try {
      const assetUrl = new URL(path);
      const pageUrl = window.location;
      const assetIsLoopback = isLoopbackHost(assetUrl.hostname);
      const pageIsRemote = isRemoteMobileAccessPage(pageUrl);
      if (assetIsLoopback && pageIsRemote) {
        assetUrl.protocol = pageUrl.protocol;
        assetUrl.host = pageUrl.host;
        return assetUrl.toString();
      }
    } catch {
      // Fall through to the existing path handling.
    }
  }
  if (/^(?:[a-z][a-z\d+.-]*:|\/assets\/)/i.test(path)) {
    return path;
  }
  return fileUrl(path);
}

export function transportStatusText(
  t: (key: MessageKey) => string,
  state: ChatTransportState,
  mode: ChatTransportMode,
) {
  if (state === "connected") {
    return mode === "websocket" ? t("chat.transport.connected") : t("chat.transport.snapshot");
  }
  if (state === "polling") {
    return t("chat.transport.polling");
  }
  if (state === "reconnecting") {
    return t("chat.transport.reconnecting");
  }
  return t("chat.transport.connecting");
}
