"""Independent command handlers and extensible dispatch with shared delivery policy."""

from __future__ import annotations
from typing import Any
from pathlib import Path
from collections.abc import Callable
import uuid
from urllib.parse import quote
from core.chat_history.storage import (
    chat_history_active_path,
    remove_chat_history_storage,
)
from core.media.chat_attachments import (
    resolve_chat_attachments,
    chat_attachment_display_text,
)
from core.story import SelectChoice
from sdk.path_utils import reject_control_chars
from application.chat.runtime_ports import HistoryPort, StorySelectionPort
from application.chat.runtime_history import (
    _plain_history_text,
    _plain_history_text_from_entries,
)


class CommandContext:
    def __init__(
        self,
        state: Any,
        body: dict[str, Any],
        snapshot: Callable[..., dict],
        runtime_commands: set[str],
    ) -> None:
        self.state, self.body, self.snapshot, self.runtime_commands = (
            state,
            body,
            snapshot,
            runtime_commands,
        )
        self.command = str(body.get("type") or "").strip()
        self.history_raw = str(state.chat_session.get("historyPath") or "").strip()
        self.session_id = str(state.chat_session.get("sessionId") or "").strip()
        self.chat_stream = getattr(state, "chat_stream", None)

    def forward(
        self,
        next_status: str,
        next_message: str = "",
        *,
        session_patch: dict[str, Any] | None = None,
        snapshot_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.command not in self.runtime_commands:
            raise ValueError(f"未知实时聊天命令：{self.command}")
        if not self.session_id or self.chat_stream is None:
            raise RuntimeError("当前聊天会话未连接到实时流。")
        runtime_command = dict(self.body)
        runtime_command["cmdId"] = str(self.body.get("cmdId") or uuid.uuid4().hex)
        if not self.chat_stream.send_command(self.session_id, runtime_command):
            raise RuntimeError("实时聊天会话未就绪，无法发送命令。")
        if session_patch:
            self.state.chat_session = {**self.state.chat_session, **session_patch}
        next_snapshot = {
            "numericInfo": next_status,
            "sessionClosedReason": "",
            "status": next_status,
        }
        current_snapshot = self.chat_stream.get_snapshot(self.session_id)
        if (
            isinstance(current_snapshot, dict)
            and str(current_snapshot.get("sessionClosedReason") or "").strip()
        ):
            next_snapshot["notificationText"] = ""
        if next_message:
            next_snapshot["dialogText"] = next_message
            next_snapshot["dialogHtml"] = None
            next_snapshot["characterName"] = ""
        if snapshot_patch:
            next_snapshot.update(snapshot_patch)
        self.chat_stream.update_session_snapshot(self.session_id, next_snapshot)
        return self.snapshot(
            self.state, next_status, next_message, extra=snapshot_patch
        )

    def current_status(self) -> str:
        if self.session_id and self.chat_stream is not None:
            snapshot = self.chat_stream.get_snapshot(self.session_id)
            if isinstance(snapshot, dict):
                status = str(snapshot.get("status") or "").strip()
                if status:
                    return status
        return "idle"


CommandHandler = Callable[[CommandContext], dict[str, Any]]


class ChatCommandRouter:
    """Extend by registering a handler; dispatch and transport policy stay fixed."""

    def __init__(self, snapshot: Callable[..., dict]) -> None:
        self.snapshot = snapshot
        self.handlers: dict[str, CommandHandler] = {}
        self.runtime_commands: set[str] = set()

    def register(
        self, command: str, handler: CommandHandler, *, runtime: bool = True
    ) -> None:
        if not command or not callable(handler):
            raise ValueError("A command name and callable handler are required.")
        if command in self.handlers:
            raise ValueError(f"Command already registered: {command}")
        self.handlers[command] = handler
        if runtime:
            self.runtime_commands.add(command)

    def handle(self, state: Any, body: dict[str, Any]) -> dict[str, Any]:
        context = CommandContext(state, body, self.snapshot, self.runtime_commands)
        handler = self.handlers.get(context.command)
        if handler is None:
            raise ValueError(f"未知聊天命令：{context.command}")
        return handler(context)


class HistoryCommands:
    def __init__(
        self,
        *,
        history: HistoryPort,
        download_file: Callable[[Any], Path],
        issue_download: Callable[[Any, Path], str],
        discard_story: Callable[[Any], None],
    ) -> None:
        self.history, self.download_file, self.issue_download, self.discard_story = (
            history,
            download_file,
            issue_download,
            discard_story,
        )

    def copy_history(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        history_raw = ctx.history_raw
        entries = self.history.entries(state)
        text = _plain_history_text_from_entries(entries)
        opened_path = history_raw
        if not text:
            if not history_raw:
                raise FileNotFoundError("没有已关联的聊天历史文件。")
            history_path = self.history.resolve(state, history_raw)
            history_file = chat_history_active_path(history_path)
            if not history_file.exists():
                raise FileNotFoundError(history_file.as_posix())
            text = _plain_history_text(self.history.read(history_file))
            opened_path = history_file.as_posix()
        return ctx.snapshot(
            state,
            "idle",
            "历史记录已复制。",
            extra={"clipboardText": text, "openedPath": opened_path},
        )

    def open_history(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        history_file = self.download_file(state)
        capability = self.issue_download(state, history_file)
        return ctx.snapshot(
            state,
            "idle",
            "历史文件已打开。",
            extra={
                "downloadUrl": f"/api/chat/history-file?cap={quote(capability, safe='')}",
                "openedPath": history_file.as_posix(),
            },
        )

    def clear_history(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        history_raw = ctx.history_raw
        session_id = ctx.session_id
        chat_stream = ctx.chat_stream
        self.discard_story(state)
        if session_id and chat_stream is not None:
            return ctx.forward(
                "idle",
                "历史记录已经清空。",
                snapshot_patch={"historyEntries": [], "options": []},
            )
        if not history_raw:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        history_path = self.history.resolve(state, history_raw)
        remove_chat_history_storage(history_path)
        return ctx.snapshot(
            state,
            "idle",
            "历史记录已经清空。",
            extra={"historyEntries": [], "options": []},
        )


def dismiss_plugin_page(ctx: CommandContext) -> dict[str, Any]:
    state = ctx.state
    body = ctx.body
    session_id = ctx.session_id
    chat_stream = ctx.chat_stream
    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Plugin page dismissal must be an object.")
    plugin_id = reject_control_chars(
        str(payload.get("pluginId") or "").strip(), field="pluginId"
    )
    presentation_id = reject_control_chars(
        str(payload.get("presentationId") or "").strip(), field="presentationId"
    )
    if not plugin_id or not presentation_id:
        raise ValueError("Plugin page dismissal requires pluginId and presentationId.")
    if len(plugin_id) > 128 or len(presentation_id) > 128:
        raise ValueError("Plugin page dismissal identifiers are too long.")
    body["payload"] = {"pluginId": plugin_id, "presentationId": presentation_id}
    if not session_id or chat_stream is None:
        raise RuntimeError("当前聊天会话未连接到实时流。")
    if not chat_stream.publish_event(
        session_id,
        {
            "type": "plugin.page.dismiss",
            "pluginId": plugin_id,
            "presentationId": presentation_id,
        },
    ):
        raise RuntimeError("无法关闭插件页面展示。")
    return ctx.snapshot(state, ctx.current_status())


class TurnOptionsCommands:
    def __init__(self, turn_options: Callable[[Any], dict]) -> None:
        self.turn_options = turn_options

    def update(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Chat turn options must be an object.")
        interrupt_enabled = payload.get("interruptEnabled")
        batch_enabled = payload.get("batchEnabled")
        batch_idle_seconds = payload.get("batchIdleSeconds")
        if not isinstance(interrupt_enabled, bool) or not isinstance(
            batch_enabled, bool
        ):
            raise ValueError("Chat turn switches must be boolean values.")
        if isinstance(batch_idle_seconds, bool) or not isinstance(
            batch_idle_seconds, (int, float)
        ):
            raise ValueError("Batch input timeout must be numeric.")
        timeout = float(batch_idle_seconds)
        if not 0.3 <= timeout <= 120.0:
            raise ValueError("Batch input timeout must be between 0.3 and 120 seconds.")
        config_manager = state.config_manager
        previous = config_manager.config.api_config
        updated = previous.model_copy(deep=True)
        updated.interrupt_enabled = interrupt_enabled
        updated.is_batch_input_enabled = batch_enabled
        updated.batch_input_timeout = timeout
        config_manager.config.api_config = updated
        try:
            config_manager.save_api_config()
            turn_options = self.turn_options(state)
            return ctx.forward(
                ctx.current_status(), snapshot_patch={"turnOptions": turn_options}
            )
        except Exception:
            config_manager.config.api_config = previous
            try:
                config_manager.save_api_config()
            except Exception:
                pass
            raise


class InputCommands:
    def __init__(
        self, *, turn_options: Callable[[Any], dict], user_name: Callable[[Any], str]
    ) -> None:
        self.turn_options, self.user_name = turn_options, user_name

    def message(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        command = ctx.command
        attachments = []
        payload = body.get("payload")
        if command == "send-message" and isinstance(payload, dict):
            submitted_text = str(payload.get("text") or "").strip()
            raw_attachments = payload.get("attachments")
            attachments = resolve_chat_attachments(
                raw_attachments if isinstance(raw_attachments, list) else []
            )
            body["payload"] = {
                "attachments": [attachment.to_payload() for attachment in attachments],
                "text": submitted_text,
            }
        else:
            submitted_text = str(payload or "").strip()
        if not submitted_text and (not attachments):
            raise ValueError(
                "选项不能为空。" if command == "submit-option" else "消息内容不能为空。"
            )
        if self.turn_options(state)["batchEnabled"]:
            snapshot_patch: dict[str, Any] = {"inputDraft": ""}
            if command == "send-message":
                snapshot_patch["userDisplayName"] = self.user_name(state)
            return ctx.forward(ctx.current_status(), snapshot_patch=snapshot_patch)
        if command == "submit-option":
            return ctx.forward("generating", f"已选择：{submitted_text}")
        user_display_name = self.user_name(state)
        return ctx.forward(
            "generating",
            chat_attachment_display_text(submitted_text, attachments),
            snapshot_patch={
                "characterName": user_display_name,
                "inputDraft": "",
                "userDisplayName": user_display_name,
            },
        )


class SelectionCommands:
    def __init__(
        self,
        *,
        story: StorySelectionPort,
        record_choice: Callable[[Any, str], list[dict]],
        choice_label: Callable[[Any, str], str],
        text_selection: CommandHandler,
    ) -> None:
        self.story, self.record_choice, self.choice_label, self.text_selection = (
            story,
            record_choice,
            choice_label,
            text_selection,
        )

    def submit(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        if not isinstance(body.get("payload"), dict):
            return self.text_selection(ctx)
        payload = body["payload"]
        if payload.get("kind") == "story-choice":
            story_session = self.story.session(state)
            if story_session is None:
                raise ValueError("Option selection must be a string.")
            choice_id = reject_control_chars(
                str(payload.get("choiceId") or "").strip(), field="choiceId"
            )
            expected_node_id = reject_control_chars(
                str(payload.get("expectedNodeId") or "").strip(), field="expectedNodeId"
            )
            try:
                expected_revision = int(payload.get("expectedRevision"))
            except (TypeError, ValueError) as exc:
                raise ValueError("Story choice revision is invalid.") from exc
            if not choice_id or not expected_node_id:
                raise ValueError("Story choice is invalid.")
            command_id = str(body.get("cmdId") or uuid.uuid4().hex)
            history_entries = self.record_choice(
                state, self.choice_label(story_session, choice_id)
            )
            ack = story_session.execute(
                SelectChoice(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    choice_id=choice_id,
                    expected_node_id=expected_node_id,
                ),
                history_entries=history_entries,
            )
            patch = story_session.chat_snapshot()
            patch["storyAck"] = ack.to_payload()
            self.story.publish(
                state,
                patch,
                history_entries=history_entries,
                presentation_events=ack.presentation_events,
            )
            return ctx.snapshot(state, "idle", extra=patch)
        if payload.get("kind") != "tool-confirmation":
            raise ValueError("Option selection must be a string.")
        confirmation_id = reject_control_chars(
            str(payload.get("confirmationId") or "").strip(), field="confirmationId"
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
        return ctx.forward(ctx.current_status())


def input_batch(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward(ctx.current_status())


def audio_playback(ctx: CommandContext) -> dict[str, Any]:
    body = ctx.body
    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Audio playback signal must be an object.")
    playback_id = reject_control_chars(
        str(payload.get("playbackId") or "").strip(), field="playbackId"
    )
    renderer_id = reject_control_chars(
        str(payload.get("rendererId") or "").strip(), field="rendererId"
    )
    playback_state = str(payload.get("state") or "").strip()
    if (
        not playback_id
        or not renderer_id
        or playback_state not in {"started", "finished", "interrupted", "failed"}
    ):
        raise ValueError("Audio playback signal is invalid.")
    body["payload"] = {
        "playbackId": playback_id,
        "rendererId": renderer_id[:128],
        "state": playback_state,
        "error": str(payload.get("error") or "")[:500],
    }
    return ctx.forward(ctx.current_status())


def skip_speech(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward("idle", "已跳过当前语音。")


def advance(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward("idle")


def voice_language(ctx: CommandContext) -> dict[str, Any]:
    body = ctx.body
    voice_language = str(body.get("payload") or "").strip().lower()
    if not voice_language:
        raise ValueError("语音语言不能为空。")
    return ctx.forward(
        "idle",
        session_patch={"voiceLanguage": voice_language},
        snapshot_patch={"voiceLanguage": voice_language},
    )


def pause_asr(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward("paused", "语音识别已暂停。")


def resume_asr(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward("listening", "语音识别已恢复。")


def asr_hold(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward(ctx.current_status())


def reroll(ctx: CommandContext) -> dict[str, Any]:
    return ctx.forward("generating", "正在请求重新生成。")


class BranchCommands:
    def __init__(
        self,
        *,
        features: Callable[[Any], dict],
        sync: Callable[[Any, str, dict], None],
        publish: Callable[[Any], None],
    ) -> None:
        self.features, self.sync, self.publish = features, sync, publish

    def revert(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        command = ctx.command
        try:
            int(body.get("payload"))
        except (TypeError, ValueError) as exc:
            raise ValueError("回溯索引无效。") from exc
        self.sync(state, command, body)
        result = ctx.forward("idle")
        self.publish(state)
        return result

    def fork(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        command = ctx.command
        if not self.features(state)["forkHistory"]:
            raise PermissionError("React Chat UI Fork 实验功能未启用。")
        payload = body.get("payload")
        raw_index = payload.get("userIndex") if isinstance(payload, dict) else payload
        try:
            int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("分支索引无效。") from exc
        self.sync(state, command, body)
        result = ctx.forward("generating", "正在创建对话分支。")
        self.publish(state)
        return result

    def switch(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        command = ctx.command
        if not self.features(state)["conversationTree"]:
            raise PermissionError("React Chat UI 分支流程图实验功能未启用。")
        branch_id = str(body.get("payload") or "").strip()
        if not branch_id:
            raise ValueError("分支 id 不能为空。")
        self.sync(state, command, body)
        result = ctx.forward("idle", "已切换对话分支。")
        self.publish(state)
        return result

    def rename(self, ctx: CommandContext) -> dict[str, Any]:
        state = ctx.state
        body = ctx.body
        if not self.features(state)["conversationTree"]:
            raise PermissionError("React Chat UI 分支流程图实验功能未启用。")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("分支重命名参数无效。")
        branch_id = str(payload.get("branchId") or "").strip()
        label = str(payload.get("label") or "").strip()
        if not branch_id:
            raise ValueError("分支 id 不能为空。")
        if not label:
            raise ValueError("分支名称不能为空。")
        return ctx.forward("idle", "已重命名对话分支。")
