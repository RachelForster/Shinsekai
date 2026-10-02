"""Builtin input, plugin-page, speech and ASR command handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from application.chat.dispatch_commands import CommandContext, CommandRegistry
from config.schema import ApiConfig
from core.media.chat_attachments import chat_attachment_display_text, resolve_chat_attachments
from sdk.path_utils import reject_control_chars


@dataclass(frozen=True)
class TurnOptionsStore:
    read: Callable[[], ApiConfig]
    replace: Callable[[ApiConfig], None]
    save: Callable[[], None]


@dataclass(frozen=True)
class ChatCommandBindings:
    turn_options: Callable[[], dict[str, Any]]
    user_display_name: Callable[[], str]
    turn_options_store: TurnOptionsStore


def register_chat_commands(registry: CommandRegistry, bindings: ChatCommandBindings) -> None:

    def dismiss_plugin_page(context: CommandContext) -> dict[str, Any]:
        body = context.body
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Plugin page dismissal must be an object.")
        plugin_id = reject_control_chars(
            str(payload.get("pluginId") or "").strip(),
            field="pluginId",
        )
        presentation_id = reject_control_chars(
            str(payload.get("presentationId") or "").strip(),
            field="presentationId",
        )
        if not plugin_id or not presentation_id:
            raise ValueError("Plugin page dismissal requires pluginId and presentationId.")
        if len(plugin_id) > 128 or len(presentation_id) > 128:
            raise ValueError("Plugin page dismissal identifiers are too long.")
        body["payload"] = {
            "pluginId": plugin_id,
            "presentationId": presentation_id,
        }
        if not context.ports.session_id or context.ports.stream is None:
            raise RuntimeError("当前聊天会话未连接到实时流。")
        if not context.ports.stream.publish_event(
            context.ports.session_id,
            {
                "type": "plugin.page.dismiss",
                "pluginId": plugin_id,
                "presentationId": presentation_id,
            },
        ):
            raise RuntimeError("无法关闭插件页面展示。")
        return context.ports.snapshot(context.ports.current_status())

    registry.register("dismiss-plugin-page", dismiss_plugin_page)

    def update_turn_options(context: CommandContext) -> dict[str, Any]:
        body = context.body
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Chat turn options must be an object.")
        interrupt_enabled = payload.get("interruptEnabled")
        batch_enabled = payload.get("batchEnabled")
        batch_idle_seconds = payload.get("batchIdleSeconds")
        if not isinstance(interrupt_enabled, bool) or not isinstance(batch_enabled, bool):
            raise ValueError("Chat turn switches must be boolean values.")
        if isinstance(batch_idle_seconds, bool) or not isinstance(batch_idle_seconds, (int, float)):
            raise ValueError("Batch input timeout must be numeric.")
        timeout = float(batch_idle_seconds)
        if not 0.3 <= timeout <= 120.0:
            raise ValueError("Batch input timeout must be between 0.3 and 120 seconds.")

        store = bindings.turn_options_store
        previous = store.read()
        updated = previous.model_copy(deep=True)
        updated.interrupt_enabled = interrupt_enabled
        updated.is_batch_input_enabled = batch_enabled
        updated.batch_input_timeout = timeout
        store.replace(updated)
        try:
            store.save()
            turn_options = bindings.turn_options()
            return context.forward(
                context.ports.current_status(),
                snapshot_patch={"turnOptions": turn_options},
            )
        except Exception:
            store.replace(previous)
            try:
                store.save()
            except Exception:
                pass
            raise

    registry.register("update-turn-options", update_turn_options)

    def audio_playback(context: CommandContext) -> dict[str, Any]:
        body = context.body
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Audio playback signal must be an object.")
        playback_id = reject_control_chars(
            str(payload.get("playbackId") or "").strip(),
            field="playbackId",
        )
        renderer_id = reject_control_chars(
            str(payload.get("rendererId") or "").strip(),
            field="rendererId",
        )
        playback_state = str(payload.get("state") or "").strip()
        if not playback_id or not renderer_id or playback_state not in {
            "started",
            "finished",
            "interrupted",
            "failed",
        }:
            raise ValueError("Audio playback signal is invalid.")
        body["payload"] = {
            "playbackId": playback_id,
            "rendererId": renderer_id[:128],
            "state": playback_state,
            "error": str(payload.get("error") or "")[:500],
        }
        return context.forward(context.ports.current_status())

    registry.register("audio-playback-signal", audio_playback)

    def send_text(context: CommandContext) -> dict[str, Any]:
        command = context.command
        body = context.body
        attachments = []
        payload = body.get("payload")
        if command == "send-message" and isinstance(payload, dict):
            submitted_text = str(payload.get("text") or "").strip()
            raw_attachments = payload.get("attachments")
            attachments = resolve_chat_attachments(raw_attachments if isinstance(raw_attachments, list) else [])
            body["payload"] = {
                "attachments": [attachment.to_payload() for attachment in attachments],
                "text": submitted_text,
            }
        else:
            submitted_text = str(payload or "").strip()
        if not submitted_text and not attachments:
            raise ValueError("选项不能为空。" if command == "submit-option" else "消息内容不能为空。")
        if bindings.turn_options()["batchEnabled"]:
            snapshot_patch: dict[str, Any] = {"inputDraft": ""}
            if command == "send-message":
                snapshot_patch["userDisplayName"] = bindings.user_display_name()
            return context.forward(
                context.ports.current_status(),
                snapshot_patch=snapshot_patch,
            )
        if command == "submit-option":
            return context.forward("generating", f"已选择：{submitted_text}")
        user_display_name = bindings.user_display_name()
        return context.forward(
            "generating",
            chat_attachment_display_text(submitted_text, attachments),
            snapshot_patch={
                "characterName": user_display_name,
                "inputDraft": "",
                "userDisplayName": user_display_name,
            },
        )

    registry.register("send-message", send_text)

    registry.register("submit-option", send_text)

    def voice_language(context: CommandContext) -> dict[str, Any]:
        body = context.body
        voice_language = str(body.get("payload") or "").strip().lower()
        if not voice_language:
            raise ValueError("语音语言不能为空。")
        return context.forward(
            "idle",
            session_patch={"voiceLanguage": voice_language},
            snapshot_patch={"voiceLanguage": voice_language},
        )

    registry.register("change-voice-language", voice_language)

    def tool_confirmation(context: CommandContext) -> dict[str, Any]:
        body = context.body
        payload = body["payload"]
        confirmation_id = reject_control_chars(
            str(payload.get("confirmationId") or "").strip(),
            field="confirmationId",
        )
        action = str(payload.get("action") or "").strip().casefold()
        if (
            not confirmation_id
            or len(confirmation_id) > 128
            or action not in {"confirm", "cancel"}
        ):
            raise ValueError("Tool confirmation response is invalid.")
        body["payload"] = {
            "action": action,
            "confirmationId": confirmation_id,
            "kind": "tool-confirmation",
        }
        return context.forward(context.ports.current_status())

    registry.register_option("tool-confirmation", tool_confirmation)

    def current_status(context: CommandContext) -> dict[str, Any]:
        return context.forward(context.ports.current_status())

    for command in (
        "chat-input-state", "flush-input-batch", "cancel-input-batch",
        "begin-asr-hold", "finish-asr-hold", "cancel-asr-hold",
    ):
        registry.register(command, current_status)

    responses = {
        "skip-speech": ("idle", "已跳过当前语音。"),
        "dialog-advance": ("idle", ""),
        "pause-asr": ("paused", "语音识别已暂停。"),
        "resume-asr": ("listening", "语音识别已恢复。"),
        "reroll": ("generating", "正在请求重新生成。"),
    }
    for command, (status, message) in responses.items():
        registry.register(command, lambda context, status=status, message=message: context.forward(status, message))
