const UNSAFE_URL_TEXT = /[\u0000-\u001f\u007f\\]/;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "[::1]", "localhost"]);

function hasSameBridgeHost(left: URL, right: URL) {
  const leftHost = left.hostname.toLowerCase();
  const rightHost = right.hostname.toLowerCase();
  return leftHost === rightHost || (LOOPBACK_HOSTS.has(leftHost) && LOOPBACK_HOSTS.has(rightHost));
}

export function normalizeBridgeOrigin(baseUrl: string) {
  if (!baseUrl || baseUrl !== baseUrl.trim() || UNSAFE_URL_TEXT.test(baseUrl)) {
    throw new Error("Bridge base URL must be an exact HTTP(S) origin");
  }
  const url = new URL(baseUrl);
  if (
    !/^https?:$/.test(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error("Bridge base URL must be an exact HTTP(S) origin");
  }
  return url.origin;
}

export function resolveBridgeWebSocketEndpoint(baseUrl: string, wsUrl: string) {
  if (!wsUrl || wsUrl !== wsUrl.trim() || UNSAFE_URL_TEXT.test(wsUrl) || wsUrl.includes("?")) {
    throw new Error("Bridge WebSocket URL must be an exact endpoint");
  }
  const bridge = new URL(normalizeBridgeOrigin(baseUrl));
  const socket = new URL(wsUrl);
  const expectedProtocol = bridge.protocol === "https:" ? "wss:" : "ws:";
  const bridgePort = Number(bridge.port || (bridge.protocol === "https:" ? "443" : "80"));
  const socketPort = Number(socket.port || (socket.protocol === "wss:" ? "443" : "80"));
  if (
    socket.protocol !== expectedProtocol ||
    socket.username ||
    socket.password ||
    socket.pathname !== "/ws" ||
    socket.search ||
    socket.hash ||
    !hasSameBridgeHost(bridge, socket) ||
    bridgePort >= 65535 ||
    socketPort !== bridgePort + 1
  ) {
    throw new Error("Bridge WebSocket URL does not match the active bridge endpoint");
  }
  return socket;
}

export function resolveBridgeEndpoint(baseUrl: string, path: string) {
  const base = new URL(normalizeBridgeOrigin(baseUrl));
  const url = new URL(path, base);
  if (url.origin !== base.origin) {
    throw new Error("Bridge URL must stay on the active bridge origin");
  }
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Bridge endpoint must be an origin-relative path");
  }
  return url;
}
