import { modelFileUrl } from "../files/repository";

/** Read opaque model state; validation belongs to the selected format's session. */
export async function readAvatarState(modelPath: string, path: string, signal: AbortSignal): Promise<unknown> {
  const normalizedModel = modelPath.replaceAll("\\", "/");
  const modelDirectory = normalizedModel.slice(0, normalizedModel.lastIndexOf("/") + 1);
  const relativePath = path.replaceAll("\\", "/").slice(modelDirectory.length);
  const response = await fetch(modelFileUrl(modelPath, relativePath), { signal });
  if (!response.ok) throw new Error(`State request failed: ${response.status}`);
  return response.json();
}
