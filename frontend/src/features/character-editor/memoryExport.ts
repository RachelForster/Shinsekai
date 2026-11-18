import { isTauriDesktop, saveDesktopTextExport } from "../../shared/desktop/desktopApi";

function buildExportBaseName(characterName: string): string {
  const safe = (characterName || "character").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").trim() || "character";
  return `${safe}-memories`;
}

/** Save already-rendered memory text (produced by the backend export endpoint) as a .txt file. */
export async function saveMemoriesTextFile(
  characterName: string,
  text: string,
): Promise<{ name: string; path?: string }> {
  const baseName = buildExportBaseName(characterName);
  if (isTauriDesktop()) {
    const { name, path } = await saveDesktopTextExport(baseName, text);
    return { name, path };
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const name = `${baseName}-${stamp}.txt`;
  // Prefix a BOM so Windows editors detect UTF-8 for CJK content.
  const blob = new Blob(["\uFEFF", text], { type: "text/plain;charset=utf-8" });
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 30_000);
  return { name };
}
