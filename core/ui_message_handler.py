"""
UI worker 用 TTS 输出消息处理器（见 handler_registry.UIOutputMessageHandler）。

依赖从 core.app_runtime.get_app_runtime() 取得；对话音轨使用 ui_playback 桥接。
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any, List

import pygame

from i18n import tr as tr_i18n

from config.config_manager import ConfigManager
from core.app_runtime import get_app_runtime
from core.dialog_tokens import (
    SYSTEM_UI_SKIP,
    match_bgm_name,
    match_cg_name,
    match_choice_name,
    match_scene_name,
    match_stat_name,
)
from core.handler_registry import UIOutputMessageHandler
from core.message import TTSOutputMessage

_config = ConfigManager()


def get_character_by_name(name: str):
    return _config.get_character_by_name(name)


def _ui() -> Any:
    return get_app_runtime().ui_update_manager


def _play() -> Any:
    return get_app_runtime().ui_playback


class OptionsUiHandler(UIOutputMessageHandler):
    def can_handle(self, out: TTSOutputMessage) -> bool:
        return out.is_system_message and match_choice_name(out.character_name or "")

    def handle(self, out: TTSOutputMessage) -> None:
        sp = out.speech or ""
        label = tr_i18n("dialog.option_badge")
        formatted_option = (
            f"<p style='line-height: 135%; letter-spacing: 2px; color:#84C2D5;'>"
            f"<b>{label}</b>：{sp}</p>"
        )
        _ui().chat_history.append(formatted_option)
        option_list = [p.strip() for p in sp.split("/") if p.strip()]
        _ui().post_options(option_list)


class NumericUiHandler(UIOutputMessageHandler):
    def can_handle(self, out: TTSOutputMessage) -> bool:
        return out.is_system_message and match_stat_name(out.character_name or "")

    def handle(self, out: TTSOutputMessage) -> None:
        _ui().post_numeric_value(out.speech or "")


class SceneUiHandler(UIOutputMessageHandler):
    def can_handle(self, out: TTSOutputMessage) -> bool:
        return out.is_system_message and match_scene_name(out.character_name or "")

    def handle(self, out: TTSOutputMessage) -> None:
        try:
            idx = int(out.sprite) - 1
            bg = _ui().bg_group
            if idx < 0 or idx >= len(bg):
                raise IndexError("背景图片的index不正常")
            bg_path = Path(bg[idx].get("path")).as_posix()
            _ui().post_background(bg_path)
        except Exception as e:
            traceback.print_exc()
            print("更新背景失败", e)


class BgmUiHandler(UIOutputMessageHandler):
    def can_handle(self, out: TTSOutputMessage) -> bool:
        return out.is_system_message and match_bgm_name(out.character_name or "")

    def handle(self, out: TTSOutputMessage) -> None:
        _ui().switch_bgm(out.audio_path or "")


class CgUiHandler(UIOutputMessageHandler):
    def can_handle(self, out: TTSOutputMessage) -> bool:
        return out.is_system_message and match_cg_name(out.character_name or "")

    def handle(self, out: TTSOutputMessage) -> None:
        try:
            path = out.audio_path or ""
            if "no person" in (out.speech or ""):
                _ui().post_background(path)
            else:
                _ui().post_cg(path)
        except Exception as e:
            print(f"更新CG失败：{e}")
            traceback.print_exc()


class SystemMiscUiHandler(UIOutputMessageHandler):
    """NARR 等其余 system 消息（有对话等待）。"""

    def can_handle(self, out: TTSOutputMessage) -> bool:
        if not out.is_system_message:
            return False
        name = out.character_name or ""
        if name in SYSTEM_UI_SKIP:
            return False
        return True

    def handle(self, out: TTSOutputMessage) -> None:
        _ui().update_dialog(out.character_name, out.speech or "", "#84C2D5")
        ev = _play().task_done_requested
        if ev and not ev.is_set():
            sp = out.speech or ""
            ev.wait(timeout=max(len(sp) / 10, 0.5))


class CharacterDialogUiHandler(UIOutputMessageHandler):
    def can_handle(self, out: TTSOutputMessage) -> bool:
        return not out.is_system_message

    def handle(self, out: TTSOutputMessage) -> None:
        rt = get_app_runtime()
        ui = rt.ui_update_manager
        ch = _play()
        character_name = out.character_name
        speech = out.speech or ""
        sprite_id = out.sprite
        audio_path = out.audio_path
        if audio_path:
            audio_path = Path(audio_path).as_posix()
        effect = out.effect
        character_config = get_character_by_name(character_name)
        fallback_color = "#84C2D5"
        if not character_config:
            print(f"UIWorker: 未找到角色配置「{character_name}」，跳过立绘；仅在有台词时用占位颜色显示")
        ui.post_notification(f"{character_name}正在回复……")
        if speech:
            color = character_config.color if character_config else fallback_color
            ui.update_dialog(character_name, speech, color, is_system=False)
        if character_config:
            try:
                ui.update_sprite(character_name, int(sprite_id) - 1)
            except (ValueError, TypeError, IndexError) as e:
                print(f"UIWorker: 立绘更新跳过（索引或数据无效）: {e}")
        ui.resolve_effect(
            effect=effect, args={"character_name": character_name}, after_dialog=False
        )
        min_stop_time = len(speech) // 8
        start_time = time.perf_counter()
        audio_played = False
        ch.current_audio_path = audio_path
        dc = ch.dialog_channel
        ev = ch.task_done_requested
        tts_sound = None
        if dc and audio_path and Path(audio_path).exists():
            try:
                tts_sound = pygame.mixer.Sound(audio_path)
                dc.play(tts_sound)
                audio_played = True
                ui.post_pause_asr()
                while dc.get_busy() and ev and not ev.is_set():
                    time.sleep(0.1)
                time.sleep(0.2)
                ui.post_llm_reply_finished()
            except Exception as e:
                print(f"UIWorker: 播放音频时出错: {e}")
            finally:
                if audio_played and tts_sound is not None:
                    try:
                        pygame.mixer.Sound.stop(tts_sound)
                    except Exception:
                        pass
                ch.current_audio_path = None
        end_time = time.perf_counter()
        if ev and not ev.is_set():
            remaining = min_stop_time - (end_time - start_time)
            if remaining > 0:
                ev.wait(timeout=remaining)
        rt.audio_path_queue.task_done()

    def post_process(self, out: TTSOutputMessage) -> None:
        get_app_runtime().ui_update_manager.resolve_effect(
            effect=out.effect,
            args={"character_name": out.character_name},
            after_dialog=True,
        )


def get_ui_output_handlers() -> List[UIOutputMessageHandler]:
    return [
        OptionsUiHandler(),
        NumericUiHandler(),
        SceneUiHandler(),
        BgmUiHandler(),
        CgUiHandler(),
        SystemMiscUiHandler(),
        CharacterDialogUiHandler(),
    ]