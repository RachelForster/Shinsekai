"""Theme token extraction and localized player labels for VN export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.storage.chat_theme_store import read_chat_theme_manifest
from sdk.lang import normalize_lang

_PLAYER_UI_LABELS: dict[str, dict[str, str]] = {
    "zh_CN": {
        "start": "开始游玩",
        "continueGame": "继续游玩",
        "linesCount": "{count} 句台词",
        "voicesCount": "{count} 句配音",
        "autoPlay": "自动",
        "skip": "快进",
        "backlog": "历史",
        "replayVoice": "重听",
        "save": "存档",
        "load": "读档",
        "hideUi": "隐藏界面",
        "settings": "设置",
        "titleScreen": "标题",
        "restoreUiHint": "点击画面或按 H / Esc 恢复界面",
        "cgExit": "收起 CG",
        "cgView": "查看 CG",
        "selectedBadge": "当时选择",
        "modalClose": "关闭",
        "backlogTitle": "对话历史",
        "jumpHere": "跳转此处",
        "saveTitle": "存档",
        "loadTitle": "读取存档",
        "autosaveSlot": "自动存档",
        "manualSlot": "存档位 {slot}",
        "emptySlot": "空存档",
        "settingsTitle": "播放设置",
        "typeSpeed": "文字速度",
        "autoDelay": "自动等待 (秒)",
        "bgmVolume": "背景音乐音量",
        "ambientVolume": "环境音效音量",
        "voiceVolume": "角色配音音量",
        "autoPlayVoice": "自动播放配音",
        "endTitle": "故事到此为止",
        "endRestart": "回到开头",
        "endBackTitle": "返回标题页",
        "narration": "旁白",
        "system": "系统",
    },
    "en": {
        "start": "Start",
        "continueGame": "Continue",
        "linesCount": "{count} lines",
        "voicesCount": "{count} voices",
        "autoPlay": "Auto",
        "skip": "Skip",
        "backlog": "Log",
        "replayVoice": "Voice",
        "save": "Save",
        "load": "Load",
        "hideUi": "Hide UI",
        "settings": "Settings",
        "titleScreen": "Title",
        "restoreUiHint": "Click or press H / Esc to show UI",
        "cgExit": "Hide CG",
        "cgView": "View CG",
        "selectedBadge": "Chosen",
        "modalClose": "Close",
        "backlogTitle": "Dialogue Log",
        "jumpHere": "Jump here",
        "saveTitle": "Save",
        "loadTitle": "Load",
        "autosaveSlot": "Autosave",
        "manualSlot": "Slot {slot}",
        "emptySlot": "Empty",
        "settingsTitle": "Playback Settings",
        "typeSpeed": "Text speed",
        "autoDelay": "Auto delay (s)",
        "bgmVolume": "BGM volume",
        "ambientVolume": "Ambient volume",
        "voiceVolume": "Voice volume",
        "autoPlayVoice": "Auto-play voice",
        "endTitle": "End of Story",
        "endRestart": "Restart",
        "endBackTitle": "Back to Title",
        "narration": "Narration",
        "system": "System",
    },
    "ja": {
        "start": "はじめる",
        "continueGame": "つづきから",
        "linesCount": "{count} セリフ",
        "voicesCount": "{count} ボイス",
        "autoPlay": "オート",
        "skip": "スキップ",
        "backlog": "履歴",
        "replayVoice": "再生",
        "save": "セーブ",
        "load": "ロード",
        "hideUi": "UI非表示",
        "settings": "設定",
        "titleScreen": "タイトル",
        "restoreUiHint": "クリックまたは H / Esc で UI を表示",
        "cgExit": "CG を閉じる",
        "cgView": "CG を見る",
        "selectedBadge": "選択済み",
        "modalClose": "閉じる",
        "backlogTitle": "バックログ",
        "jumpHere": "ここへ移動",
        "saveTitle": "セーブ",
        "loadTitle": "ロード",
        "autosaveSlot": "オートセーブ",
        "manualSlot": "スロット {slot}",
        "emptySlot": "空きスロット",
        "settingsTitle": "再生設定",
        "typeSpeed": "文字速度",
        "autoDelay": "オート待機 (秒)",
        "bgmVolume": "BGM 音量",
        "ambientVolume": "環境音音量",
        "voiceVolume": "ボイス音量",
        "autoPlayVoice": "ボイス自動再生",
        "endTitle": "おわり",
        "endRestart": "最初から",
        "endBackTitle": "タイトルへ",
        "narration": "ナレーション",
        "system": "システム",
    },
}


def player_ui_labels(locale: str) -> dict[str, str]:
    """Return localized UI labels for the standalone exported VN player."""
    return dict(_PLAYER_UI_LABELS[normalize_lang(locale)])


def extract_vn_theme_vars(project_root: Path, theme_id: str, fallback_accent: str = "") -> dict[str, str]:
    """Map active Shinsekai chat theme tokens to safe ``--vn-*`` CSS variables."""
    manifest = read_chat_theme_manifest(project_root, theme_id)
    tokens = manifest.get("tokens") if isinstance(manifest.get("tokens"), dict) else {}
    global_tok = tokens.get("global") if isinstance(tokens.get("global"), dict) else {}
    dialog_tok = tokens.get("dialog") if isinstance(tokens.get("dialog"), dict) else {}
    name_tok = tokens.get("name") if isinstance(tokens.get("name"), dict) else {}
    opts_tok = tokens.get("options") if isinstance(tokens.get("options"), dict) else {}

    mapping = {
        "--vn-accent": global_tok.get("themeColor") or fallback_accent,
        "--vn-font-family": global_tok.get("fontFamily"),
        "--vn-dialog-bg": dialog_tok.get("background"),
        "--vn-dialog-border": dialog_tok.get("borderColor"),
        "--vn-dialog-color": dialog_tok.get("color"),
        "--vn-dialog-radius": dialog_tok.get("borderRadius"),
        "--vn-name-bg": name_tok.get("background"),
        "--vn-name-border": name_tok.get("borderColor"),
        "--vn-name-color": name_tok.get("color"),
        "--vn-option-bg": opts_tok.get("background"),
        "--vn-option-border": opts_tok.get("borderColor"),
        "--vn-option-color": opts_tok.get("color"),
    }
    return {k: str(v).strip() for k, v in mapping.items() if isinstance(v, str) and v.strip()}


__all__ = ["extract_vn_theme_vars", "player_ui_labels"]
