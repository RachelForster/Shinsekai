function makeRendererId() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return `renderer-${globalThis.crypto.randomUUID()}`;
  }
  return `renderer-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

const rendererId = makeRendererId();

/** Unique identity for this browser page's chat audio renderer. */
export function currentChatRendererId() {
  return rendererId;
}
