import type { AvatarFormat } from "./contracts";

const formats = new Map<string, AvatarFormat<unknown, unknown>>();

/** 注册一个模型形象格式。新增格式只需在自己的模块里调用一次。 */
export function registerAvatarFormat<S, C>(format: AvatarFormat<S, C>): void {
  const id = format.id.trim().toLowerCase();
  if (!id) {
    throw new Error("avatar format id cannot be empty");
  }
  if (id === "static") {
    throw new Error("'static' is a reserved avatar type");
  }
  if (formats.has(id)) {
    throw new Error(`duplicate avatar format: ${id}`);
  }
  let loaded: Promise<Awaited<ReturnType<typeof format.load>>> | undefined;
  formats.set(id, {
    ...format,
    id,
    load: () => {
      loaded ??= Promise.resolve()
        .then(() => format.load())
        .catch((error) => {
          loaded = undefined;
          throw error;
        });
      return loaded;
    },
  } as AvatarFormat<unknown, unknown>);
}

export function avatarFormat(id: string): AvatarFormat<unknown, unknown> | undefined {
  return formats.get(id.trim().toLowerCase());
}

export function registeredAvatarFormats(): AvatarFormat<unknown, unknown>[] {
  return [...formats.values()];
}

/** 仅测试使用：清空注册表，避免用例间串状态。 */
export function clearRegisteredAvatarFormats(): void {
  formats.clear();
}
