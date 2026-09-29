import { modelFileUrl } from "../files/repository";

/** Resolve a state through the same authorized model package route used by editors and previews. */
export function avatarStateUrl(modelPath: string, path: string): string {
  const normalizedModel = modelPath.replaceAll("\\", "/");
  const modelDirectory = normalizedModel.slice(0, normalizedModel.lastIndexOf("/") + 1);
  const relativePath = path.replaceAll("\\", "/").slice(modelDirectory.length);
  return modelFileUrl(modelPath, relativePath);
}

/** Read opaque model state; validation belongs to the selected format's session. */
export async function readAvatarState(modelPath: string, path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(avatarStateUrl(modelPath, path), { signal });
  if (!response.ok) throw new Error(`State request failed: ${response.status}`);
  return response.json();
}
