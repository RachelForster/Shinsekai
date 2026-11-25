import type { ChatVnExportMessageKey } from "../en/chatVnExport";

export const chatVnExportJaMessages: Record<ChatVnExportMessageKey, string> = {
  "chat.vnExport.button": "プレイ可能 VN を書き出す",
  "chat.vnExport.dialogTitle": "プレイ可能ビジュアルノベル書き出し（HTML / CSS / JS）",
  "chat.vnExport.rangeHint": "選択した {count} 件のセリフをローカル再生や Bilibili Toy 公開向けに書き出します。",
  "chat.vnExport.titleLabel": "作品タイトル",
  "chat.vnExport.titlePlaceholder": "タイトルを入力（空欄時は会話名を使用）",
  "chat.vnExport.subtitleLabel": "サブタイトル / 紹介（任意）",
  "chat.vnExport.subtitlePlaceholder": "タイトル画面に表示されます",
  "chat.vnExport.formatLabel": "書き出し形式",
  "chat.vnExport.formatZip": "ZIP アーカイブ（ダウンロード / Toy アップロード向け）",
  "chat.vnExport.formatDirectory": "フォルダー出力（確認・手動編集向け）",
  "chat.vnExport.outputDirLabel": "保存先パス（任意）",
  "chat.vnExport.outputDirPlaceholder": "空欄時は output/vn_exports に保存します",
  "chat.vnExport.includeVoices": "保存済みボイスを含める",
  "chat.vnExport.transcodeMp3": "MP3 へ変換して軽量化（ローカル ffmpeg が必要）",
  "chat.vnExport.includeBgm": "BGM を含める",
  "chat.vnExport.includeAmbient": "環境エフェクト・環境音を含める",
  "chat.vnExport.playerNameLabel": "プレイヤー名の置換（任意）",
  "chat.vnExport.playerNamePlaceholder": "空欄時は元の表示名をそのまま使用",
  "chat.vnExport.openFolder": "書き出し後にフォルダーを開く",
  "chat.vnExport.back": "戻る",
  "chat.vnExport.submit": "書き出し開始",
  "chat.vnExport.exporting": "ビジュアルノベルを生成中…",
  "chat.vnExport.readyTitle": "ビジュアルノベルを書き出しました",
  "chat.vnExport.summaryStats": "{entries} セリフ · {assets} 素材 · {voices} ボイス（うち MP3 変換 {mp3} 件）",
  "chat.vnExport.packageSize": "合計サイズ：{total}（index.html：{indexKb} KB）",
  "chat.vnExport.downloadZip": "ZIP をダウンロード",
  "chat.vnExport.toyHint":
    "index.html を開いてすぐ遊べるほか、Toy CLI（toy create <出力先>）でプレビューして Bilibili Toy に公開できます。",
  "chat.vnExport.warning.ffmpegUnavailable":
    "ローカルの ffmpeg が見つからないため、ボイスは元の形式のまま同梱されました。",
  "chat.vnExport.warning.skippedNonStatic":
    "静止画・動画立ち絵のみ対応しているため、{count} 件の Live2D/MMD 立ち絵をスキップしました。",
  "chat.vnExport.warning.missingAssets": "一部の履歴アセットがディスク上に見つからずスキップされました。",
};
