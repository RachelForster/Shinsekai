// @vitest-environment node
import ts from "typescript";
import { describe, expect, it } from "vitest";

const visual = "modules/character-visual";
const adapters = `${visual}/adapters/`;
const composition = "app/avatarFormats.ts";
const sources = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>("../../{app,entities,features,modules,shared}/**/*.{ts,tsx}", {
      eager: true,
      query: "?raw",
      import: "default",
    }),
  ).map(([path, code]) => [path.replace(/^\.\.\/\.\.\//, ""), code]),
);

function dependencies(file: string, code: string) {
  const imports = ts.preProcessFile(code, true, true).importedFiles.map((item) => item.fileName);
  const tree = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true);
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && /^import\.meta\.glob(?:Eager)?$/.test(node.expression.getText(tree))) {
      const argument = node.arguments[0];
      const patterns = argument && ts.isArrayLiteralExpression(argument) ? argument.elements : [argument];
      for (const pattern of patterns) if (pattern && ts.isStringLiteralLike(pattern)) imports.push(pattern.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  return imports.map((path) =>
    path.startsWith(".") ? new URL(path, `https://source/${file}`).pathname.slice(1) : path,
  );
}

function violations(file: string, code: string) {
  return dependencies(file, code).flatMap((target) => {
    const errors: string[] = [];
    const inVisual = file.startsWith(`${visual}/`);
    const inAdapter = file.startsWith(adapters);
    const toVisual = target === visual || target.startsWith(`${visual}/`);
    if (/^(entities|shared)\//.test(file) && toVisual) errors.push("domain/shared must not depend on rendering");
    if (inVisual && /^(entities|features|app)\//.test(target))
      errors.push("rendering must not depend on business orchestration or persistence");
    if (inVisual && /^shared\/(platform|desktop)\//.test(target))
      errors.push("rendering must not call application platform adapters");
    if (!inAdapter && /(?:^|[/@-])(?:cubism|live2d|pixi-live2d)/i.test(target))
      errors.push("SDK imports belong to format adapters");
    if (target.startsWith(adapters)) {
      const ownFormat = inAdapter ? file.slice(adapters.length).split("/")[0] : undefined;
      const targetFormat = target.slice(adapters.length).split("/")[0];
      const discovery = file === composition && target === `${adapters}*/format.ts`;
      if (!discovery && (!ownFormat || ownFormat !== targetFormat))
        errors.push("concrete formats are isolated; only app discovers descriptors");
    }
    if (
      !inVisual &&
      toVisual &&
      target !== visual &&
      target !== `${visual}/index` &&
      target !== `${visual}/index.ts` &&
      file !== composition
    ) {
      errors.push("consumers must use the public rendering API");
    }
    return errors.map((error) => `${file} -> ${target}: ${error}`);
  });
}

describe("character visual architecture", () => {
  it("keeps domain data, rendering and concrete adapters behind their boundaries", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(100);
    expect(sources[`${visual}/contracts.ts`]).toBeDefined();
    expect(Object.entries(sources).flatMap(([file, code]) => violations(file, code))).toEqual([]);
  });

  it.each([
    ["entities/character/assets.ts", 'import type { AvatarSession } from "../../modules/character-visual";'],
    [`${visual}/contracts.ts`, 'import type { Character } from "../../entities/config/types";'],
    [`${visual}/CharacterVisual.tsx`, 'export { create } from "./adapters/l2d/module";'],
    [
      "features/chat-stage/Stage.tsx",
      'const load = () => import("../../modules/character-visual/adapters/l2d/module");',
    ],
    [`${visual}/adapters/demo/module.ts`, 'export * from "../l2d/module";'],
    [`${visual}/registry.ts`, 'const formats = import.meta.glob("./adapters/*/format.ts");'],
    ["shared/ui/Portrait.tsx", 'export * from "../../modules/character-visual";'],
    [`${visual}/CharacterVisual.tsx`, 'import { getPlatform } from "../../shared/platform/platform";'],
    ["features/chat-stage/Stage.tsx", 'import { Live2DModel } from "pixi-live2d-display";'],
  ])("detects forbidden dependencies in %s", (file, code) => {
    expect(violations(file, code).length).toBeGreaterThan(0);
  });

  it("allows format-local implementation and app-owned descriptor discovery", () => {
    expect(
      violations(`${visual}/adapters/demo/module.ts`, 'import type { AvatarSession } from "../../contracts";'),
    ).toEqual([]);
    expect(violations(composition, sources[composition])).toEqual([]);
    expect(dependencies(composition, sources[composition])).toContain(`${adapters}*/format.ts`);
  });

  it("keeps descriptors lazy and independent of character storage defaults", () => {
    const descriptors = Object.entries(sources).filter(
      ([file]) => file.startsWith(adapters) && file.endsWith("/format.ts"),
    );
    expect(descriptors.length).toBeGreaterThan(0);
    for (const [file, code] of descriptors) {
      const tree = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true);
      const eagerImports = tree.statements.filter(
        (node) => ts.isImportDeclaration(node) && !node.importClause?.isTypeOnly,
      );
      expect(eagerImports, file).toHaveLength(0);
      expect(code, file).not.toContain("createEmpty");
    }
    expect(sources[`${visual}/contracts.ts`]).not.toContain("ModelSprites");
  });
});
