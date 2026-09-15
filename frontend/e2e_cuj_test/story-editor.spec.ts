import { expect, test } from "@playwright/test";
import type { StoryDocument, StoryEditInput } from "../src/shared/platform/storyEditorTypes";

for (const width of [1280, 760]) {
  test(`story graph editing and proposal review at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const original: StoryDocument = {
      storyPath: "stories/original.json",
      sourceHash: "original",
      version: 1,
      title: "旧校舍的秘密",
      authoringBrief: "校园悬疑。真相应在结局才揭晓，人物的反应要保持自然。",
      graph: {
        startNodeId: "opening",
        nodes: [
          {
            id: "opening",
            title: "校门前的邀约",
            type: "limited_turn_node",
            maxRounds: 3,
            instruction: "小玲邀请玩家调查旧校舍。先让玩家决定是否进入，不要提前透露真相。",
            transitions: [{ to: "ending", when: "玩家完成调查并找到证据" }],
            defaultTo: "ending",
          },
          { id: "ending", title: "真相大白", type: "ending_node", instruction: "依据玩家找到的证据揭示秘密。" },
        ],
      },
    };
    const graph = structuredClone(original.graph);
    graph.nodes[0].transitions = [{ to: "confrontation", when: "玩家找到证据" }];
    graph.nodes[0].defaultTo = "confrontation";
    graph.nodes.splice(1, 0, {
      id: "confrontation",
      title: "走廊里的对质",
      type: "free_chat_node",
      instruction: "小玲与证人核对证据，给玩家追问的机会。",
      transitions: [{ to: "ending", when: "证人解释了矛盾" }],
    });
    let saved: StoryDocument | undefined;
    const saves: StoryEditInput[] = [];
    const proposal = {
      graph,
      summary: "加入对质场景，并将调查与结局通过新节点连接。",
      validation: { valid: true, issues: [] },
    };
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body: unknown = [];
      if (["/api/config", "/api/chat/theme", "/api/chat/snapshot"].includes(path)) {
        const samples = await page.evaluate(async () => {
          const modulePath = "/src/shared/platform/sampleData.ts";
          const { sampleConfig, sampleChatTheme, sampleChatSnapshot } = await import(modulePath);
          return { sampleConfig, sampleChatTheme, sampleChatSnapshot };
        });
        if (path === "/api/config")
          body = {
            ...samples.sampleConfig,
            system_config: { ...samples.sampleConfig.system_config, story_system_enabled: true },
          };
        if (path === "/api/chat/theme") body = samples.sampleChatTheme;
        if (path === "/api/chat/snapshot") body = samples.sampleChatSnapshot;
      }
      if (path === "/api/chat/themes/active") body = { id: "" };
      if (path === "/api/chat/runtime-status") body = { state: "idle" };
      if (path === "/api/story/library")
        body = [original, ...(saved ? [saved] : [])].map((doc) => ({
          ...doc,
          id: "mystery",
          characters: ["小玲"],
          backgrounds: ["旧校舍"],
          historyPath: "",
          currentNodeTitle: "",
          updatedAt: doc.version,
        }));
      if (path === "/api/story/editor/read")
        body = route.request().postDataJSON().storyPath === saved?.storyPath ? saved : original;
      if (path === "/api/story/editor/suggest") {
        expect(route.request().postDataJSON()).toMatchObject({ scope: "graph", instructions: "加入对质场景" });
        body = { id: "proposal", status: "running" };
      }
      if (path === "/api/tasks/proposal") body = { id: "proposal", status: "succeeded", result: proposal };
      if (path === "/api/story/editor/save") {
        const input = route.request().postDataJSON();
        saves.push(input);
        saved = { ...original, ...input, version: 2, sourceHash: "revised", storyPath: "stories/edited.json" };
        body = saved;
      }
      await route.fulfill({ json: body });
    });
    await page.goto("/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8787#/settings/templates?mode=story&view=library", {
      waitUntil: "domcontentloaded",
    });
    await page.getByRole("button", { name: "编辑节点图" }).click();
    await expect(page.getByRole("heading", { name: "剧本编辑器" })).toBeVisible();
    await page.getByRole("textbox", { name: "剧情正文 / 演绎要求" }).fill("玩家来到旧校舍，与小玲核对线索。");
    await page.screenshot({ path: testInfo.outputPath("node-editor.png"), fullPage: true });
    await page.getByRole("combobox", { name: "修改范围" }).click();
    await page.getByRole("option", { name: "整个节点图（可生成新节点）" }).click();
    await page.getByRole("textbox", { name: "修改要求" }).fill("加入对质场景");
    await page.getByRole("button", { name: "生成候选修改" }).click();
    await expect(page.getByRole("region", { name: "候选修改预览" })).toBeVisible();
    expect(saves).toHaveLength(0);
    await page.screenshot({ path: testInfo.outputPath("proposal.png"), fullPage: true });
    await page.getByRole("button", { name: "采纳到草稿" }).click();
    await expect(page.getByRole("button", { name: "自由对话 走廊里的对质" })).toBeVisible();
    await page.getByRole("button", { name: "校验并保存新版本" }).click();
    await expect(page.getByRole("button", { name: "用新版本开始游玩" })).toBeVisible();
    expect(saves).toHaveLength(1);
    expect(saves[0].graph.nodes).toHaveLength(3);
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(page.getByText("版本 2", { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}
