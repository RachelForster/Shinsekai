import type { chatVnExportZhCNMessages } from "../zh_CN/chatVnExport";

export type ChatVnExportMessageKey = keyof typeof chatVnExportZhCNMessages;

export const chatVnExportEnMessages: Record<ChatVnExportMessageKey, string> = {
  "chat.vnExport.button": "Export playable VN",
  "chat.vnExport.dialogTitle": "Export Playable Visual Novel (HTML / CSS / JS)",
  "chat.vnExport.rangeHint": "Exports {count} selected dialogue entries for offline play or Bilibili Toy publishing.",
  "chat.vnExport.titleLabel": "Title",
  "chat.vnExport.titlePlaceholder": "Enter a title (defaults to conversation title)",
  "chat.vnExport.subtitleLabel": "Subtitle / description (optional)",
  "chat.vnExport.subtitlePlaceholder": "Shown on the title cover screen",
  "chat.vnExport.formatLabel": "Output format",
  "chat.vnExport.formatZip": "ZIP archive (downloadable & ready for Toy upload)",
  "chat.vnExport.formatDirectory": "Standalone folder (easy to inspect or edit)",
  "chat.vnExport.outputDirLabel": "Output path (optional)",
  "chat.vnExport.outputDirPlaceholder": "Leave blank to save under output/vn_exports",
  "chat.vnExport.includeVoices": "Include archived voice lines",
  "chat.vnExport.transcodeMp3": "Convert voices to MP3 (smaller bundle, uses local ffmpeg)",
  "chat.vnExport.includeBgm": "Include background music (BGM)",
  "chat.vnExport.includeAmbient": "Include ambient effects and audio",
  "chat.vnExport.playerNameLabel": "Player display name override (optional)",
  "chat.vnExport.playerNamePlaceholder": "Leave blank to keep the original display name",
  "chat.vnExport.openFolder": "Open output folder after export",
  "chat.vnExport.back": "Back",
  "chat.vnExport.submit": "Export VN",
  "chat.vnExport.exporting": "Packaging static visual novel…",
  "chat.vnExport.readyTitle": "Visual novel package ready",
  "chat.vnExport.summaryStats": "{entries} lines · {assets} assets · {voices} voiced lines ({mp3} converted to MP3)",
  "chat.vnExport.packageSize": "Bundle size: {total} (entry index.html: {indexKb} KB)",
  "chat.vnExport.downloadZip": "Download ZIP",
  "chat.vnExport.toyHint":
    "Double-click index.html locally to play, or run Toy CLI (toy create <exported-path>) to preview and publish to Bilibili Toy.",
  "chat.vnExport.warning.ffmpegUnavailable":
    "Local ffmpeg was not found; archived voices were packed in their original format.",
  "chat.vnExport.warning.skippedNonStatic":
    "Only static and video sprites are supported; skipped {count} Live2D/MMD sprite appearances.",
  "chat.vnExport.warning.missingAssets": "Some historical media files are missing on disk and were skipped.",
};
