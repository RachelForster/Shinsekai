import { readFileSync } from "node:fs";
import { createConnection } from "node:net";
import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Only host-supplied definitions are registered. Calls keep Pi's stable call ID.
export default function (pi: ExtensionAPI) {
  const definitions = JSON.parse(
    readFileSync(process.env.SHINSEKAI_PI_TOOLS!, "utf8"),
  );
  pi.on("session_start", async () => {
    const names = definitions.map((definition: any) => definition.nativeName);
    await requestHost({ kind: "ready", names });
    pi.setActiveTools(names);
  });
  for (const definition of definitions) {
    pi.registerTool({
      name: definition.nativeName,
      label: definition.name,
      description: `Host tool ${definition.name}: ${definition.description}`,
      parameters: Type.Unsafe(definition.inputSchema),
      async execute(callId, arguments_, signal) {
        const result: any = await requestHost(
          {
            call: { callId, name: definition.name, arguments: arguments_ },
          },
          signal,
        );
        if (!result.ok)
          throw new Error(result.error?.code || "Host tool failed");
        return {
          content: [{ type: "text", text: JSON.stringify(result.data) }],
          details: {
            artifactRefs: result.artifactRefs,
            effects: result.effects,
          },
        };
      },
    });
  }
}

function requestHost(request: object, signal?: AbortSignal): Promise<any> {
  return new Promise((resolve, reject) => {
    const socket = createConnection({
      host: "127.0.0.1",
      port: Number(process.env.SHINSEKAI_PI_HOST_PORT),
    });
    let body = Buffer.alloc(0);
    const abort = () => socket.destroy(new Error("Host call cancelled"));
    signal?.addEventListener("abort", abort, { once: true });
    socket.on("connect", () => {
      if (signal?.aborted) return abort();
      socket.write(
        JSON.stringify({
          token: process.env.SHINSEKAI_PI_HOST_TOKEN,
          ...request,
        }) + "\n",
      );
    });
    socket.on("data", (chunk) => {
      body = Buffer.concat([body, chunk]);
      if (body.length > 1024 * 1024) {
        socket.destroy(new Error("Host result exceeds the frame limit"));
        return;
      }
      const newline = body.indexOf(10);
      if (newline >= 0) {
        try {
          resolve(JSON.parse(body.subarray(0, newline).toString("utf8")));
        } catch {
          reject(new Error("Invalid host response"));
        }
        socket.end();
      }
    });
    socket.on("error", reject);
    socket.on("close", () => {
      signal?.removeEventListener("abort", abort);
      reject(new Error("Host tool connection closed"));
    });
  });
}
