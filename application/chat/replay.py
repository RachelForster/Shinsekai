"""Read-only history snapshots and explicitly requested, bounded replay synthesis."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import threading
import tempfile
import time
import uuid
from pathlib import Path

from application.chat.history.paths import resolve_history_path_for_project
from application.chat.history.state import canonical_user_turn_payload
from application.chat.replay_store import ReplayStore, replay_dialog_inputs, replay_history_messages
from application.chat.voice_archive import VoiceArchive
from core.chat_history.storage import chat_history_active_path
from core.chat_history.text import strip_local_time_prefix
from core.messaging.dialog_tokens import is_option_history_name
from application.chat.presentation.replay import PRESENTATION_KEYS


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def split_text(entry):
    match = re.match(r"^\s*([^：:\n]{1,120})[：:]\s*([\s\S]*)$", entry["text"])
    return (match[1].strip(), match[2]) if match else ("", entry["text"])


def replay_user_text(entry, body, users):
    clean = strip_local_time_prefix(body)
    index = entry.get("revertUserIndex")
    source = users[index] if type(index) is int and 0 <= index < len(users) else None
    if source and "input_text" in source:
        display = source.get("display_content") or source.get("content")
        if isinstance(display, str) and strip_local_time_prefix(display) == clean:
            return canonical_user_turn_payload(source)["text"]
    return canonical_user_turn_payload(None, fallback_text=clean)["text"]


def revision(entries):
    return digest([(e.get("id"), e.get("role"), e.get("text"), e.get("dialogId")) for e in entries])


class ChatReplayService:
    def __init__(self, state):
        self.state = state
        self.plans = {}
        self.lock = threading.RLock()
        self.synthesis_lock = threading.Lock()

    def _context(self):
        session = self.state.chat_session
        raw = str(session.get("historyPath") or "")
        if not raw:
            raise ValueError("没有可回放的聊天存档")
        path = resolve_history_path_for_project(self.state, raw)
        sid = str(session.get("sessionId") or "")
        stream = getattr(self.state, "chat_stream", None)
        snapshot = stream.get_snapshot(sid) if stream and sid else session
        snapshot = snapshot or session
        tree = snapshot.get("conversationTree") or {}
        branch = tree.get("activeBranchId", "main")
        label = next((b.get("label", branch) for b in tree.get("branches", []) if b.get("id") == branch), "")
        return path, sid, branch, label, snapshot

    @staticmethod
    def _require_idle(snapshot):
        turn = snapshot.get("turnState") or {}
        if (snapshot.get("replay") or snapshot.get("status") in {"generating", "streaming", "speaking", "initializing", "replaying"}
                or snapshot.get("asrRunning") or snapshot.get("toolConfirmation")
                or turn.get("pendingMessages") or turn.get("pendingCount", 0)):
            raise ValueError("当前回复或输入结束后可回放")

    def prepare(self):
        from application.chat.composition import _chat_history
        path, sid, branch, label, snapshot = self._context()
        self._require_idle(snapshot)
        if self.is_active():
            raise ValueError("请先退出当前回放")
        source = _chat_history(self.state)
        store = ReplayStore(path)
        messages = replay_history_messages(chat_history_active_path(path))
        legacy_by_id, legacy_by_text, speech_by_id, speech_by_text = replay_dialog_inputs(messages)
        users = [message for message in messages if message.get("role") == "user"]
        archive = VoiceArchive(path)
        config = self.state.config_manager
        url, work_path, provider = config.get_gpt_sovits_config()
        kwargs = copy.deepcopy(config.merged_tts_factory_kwargs(
            provider, {"gpt_sovits_work_path": work_path, "tts_server_url": url}
        )) if provider and provider != "none" else {}
        settings = {"provider": provider, "kwargs": kwargs, "url": url,
                    "language": str(config.config.system_config.voice_language or "ja")}
        plan_id = uuid.uuid4().hex
        plan = {"id": plan_id, "path": path, "sessionId": sid, "branchId": branch,
                "branchLabel": label, "historyCount": len(source), "revision": revision(source), "entries": [], "private": {},
                "store": store, "settings": settings, "cancelled": False, "range": None,
                "storageExisted": chat_history_active_path(path).is_file(),
                "touched": time.monotonic(), "generate": False}
        chain = digest([str(path), branch])
        frame = None
        for source_index, raw in enumerate(source):
            chain = digest([chain, raw.get("role"), raw.get("text"), raw.get("dialogId")])
            speaker, body = split_text(raw)
            user_input = raw.get("role") == "user"
            if user_input:
                body = replay_user_text(raw, body, users)
            if raw.get("role") == "system" and speaker.casefold() in {"scene", "场景", "bgm"}:
                frame = None
                continue
            dialog_id = raw.get("dialogId", "")
            key = dialog_id if re.fullmatch(r"[0-9a-f]{64}", dialog_id) else chain
            if dialog_id or raw.get("role") == "assistant":
                frame = store.read(dialog_id, "frame.json") if dialog_id else None
            recorded_message = frame.get("message") if dialog_id and frame else None
            legacy_message = legacy_by_id.get(dialog_id) or legacy_by_text.get((speaker, body))
            recorded_text = recorded_message.get("text") if isinstance(recorded_message, dict) else None
            if not isinstance(recorded_text, str):
                recorded_text = ""
            speech = speech_by_id.get(dialog_id) or speech_by_text.get((speaker, body)) or recorded_text or body
            speech_key = digest(speech)
            character = copy.deepcopy(config.get_character_by_name(speaker)) if raw.get("role") == "assistant" else None
            can_generate = bool(character and provider and provider != "none" and
                                str(getattr(character, "refer_audio_path", "") or "").strip() and speech.strip())
            paths, origin, voice_label = [], "", ""
            voice_id = raw.get("voiceId") or (archive.voice_for_dialog(dialog_id) if dialog_id else "")
            if voice_id:
                try:
                    paths = [archive.source(voice_id, index) for index in range(archive.count(voice_id))]
                    origin = "original"
                except (ValueError, OSError):
                    paths = []
            saved = store.read(key, "voice.json")
            if (not paths and saved and saved.get("speechKey", digest(body)) == speech_key
                    and re.fullmatch(r"[0-9a-f]{64}", str(saved.get("fileKey", "")))):
                audio = store.path(saved["fileKey"], "wav")
                if audio.is_file() and audio.stat().st_size:
                    paths, origin, voice_label = [audio], "generated", saved.get("label", "")
            entry = {**raw, "key": key, "position": len(plan["entries"]) + 1,
                     "speaker": speaker, "body": body,
                     **({"text": f"{speaker}: {body}" if speaker else body} if user_input else {}),
                     "frame": copy.deepcopy({k: v for k, v in frame.items() if k != "message"}) if frame is not None else None,
                     "canGenerate": can_generate, "voiceSource": origin,
                     "voiceVolume": min(1.0, max(0.0, float(getattr(character, "speech_volume", 1.0) if character else 1.0))),
                     "voiceLabel": voice_label or (f"{speaker} · {provider}" if can_generate else ""),
                     "voiceUrls": self._urls(plan_id, key, paths)}
            if raw.get("role") == "options" or is_option_history_name(speaker):
                choices = [item.strip() for item in body.split("/") if item.strip()]
                entry["options"] = choices
                # Only an exact, unique next user reply is evidence of a choice.
                # Never infer a selection from a partial label or another turn.
                for following in source[source_index + 1:]:
                    if following.get("role") == "options" or is_option_history_name(split_text(following)[0]):
                        break
                    if following.get("role") == "user":
                        selected = replay_user_text(following, split_text(following)[1], users)
                        entry["selectedIndex"] = choices.index(selected) if choices.count(selected) == 1 else None
                        break
            plan["entries"].append(entry)
            plan["private"][key] = {"character": character, "paths": paths, "speech": speech,
                                    "message": recorded_message or (legacy_message if raw.get("role") == "assistant" else None)}
        with self.lock:
            now = time.monotonic()
            for old_id, old in list(self.plans.items()):
                if now - old["touched"] > (120 if old["cancelled"] else 1800):
                    self.plans.pop(old_id, None)
            if len(self.plans) >= 32:
                raise ValueError("请关闭不再使用的回放后重试")
            self.plans[plan_id] = plan
        return {k: plan[k] for k in ("id", "sessionId", "branchId", "branchLabel", "historyCount", "entries")}

    @staticmethod
    def _urls(plan_id, key, paths):
        return [f"/api/chat/replay/{plan_id}/audio/{key}/{i}" for i in range(len(paths))]

    def _plan(self, plan_id, *, allow_cancelled=False):
        with self.lock:
            plan = self.plans.get(plan_id)
            if not plan or (plan["cancelled"] and not allow_cancelled):
                raise ValueError("回放已结束，请重新选择片段")
            path, sid, *_ = self._context()
            if path != plan["path"] or sid != plan["sessionId"]:
                plan["cancelled"] = True
                raise ValueError("聊天会话已改变，请返回聊天")
            if plan["storageExisted"] and not chat_history_active_path(path).is_file():
                plan["cancelled"] = True
                raise ValueError("聊天存档已移除，请返回聊天")
            plan["touched"] = time.monotonic()
            return plan

    def start(self, plan_id, body):
        with self.lock:
            return self._start(plan_id, body)

    def _start(self, plan_id, body):
        from application.chat.composition import _chat_history
        plan = self._plan(plan_id)
        _, _, branch, _, snapshot = self._context()
        self._require_idle(snapshot)
        if self.is_active():
            raise ValueError("请先退出当前回放")
        if branch != plan["branchId"] or revision(_chat_history(self.state)) != plan["revision"]:
            raise ValueError("历史已改变，请重新选择回放范围")
        keys = [e["key"] for e in plan["entries"]]
        try:
            start, end = keys.index(body.get("startKey")), keys.index(body.get("endKey"))
        except ValueError as exc:
            raise ValueError("请选择有效的回放起止点") from exc
        if start > end:
            raise ValueError("终点不能早于起点")
        if plan["range"] is not None:
            raise ValueError("回放已经开始")
        plan["range"] = set(keys[start:end + 1])
        plan["generate"] = body.get("generate") is True
        entries = [{**entry, "paths": [str(p) for p in plan["private"][entry["key"]]["paths"]],
                    "message": plan["private"][entry["key"]]["message"],
                    "waitForVoice": bool(plan["generate"] and entry["canGenerate"])}
                   for entry in plan["entries"][start:end + 1]]
        plan["selected"] = entries
        plan["failures"] = set()
        plan["skipped"] = set()
        plan["started"] = True
        try:
            self._send(plan, "replay-start", {"id": plan_id, "entries": entries,
                "restore": {k: copy.deepcopy(snapshot.get(k, {"sprites": [], "stats": [], "options": [], "playerPortrait": None}.get(k, ""))) for k in PRESENTATION_KEYS}})
        except Exception:
            plan["range"] = None
            plan["started"] = False
            raise
        if plan["generate"]:
            threading.Thread(target=self._prefetch, args=(plan,), name="replay-voice-prefetch", daemon=True).start()
        return {"ok": True}

    def current(self, plan_id):
        plan = self._plan(plan_id)
        if plan["range"] is None:
            raise ValueError("回放尚未开始")
        return {"generate": plan["generate"], "snapshot": {
            **{k: plan[k] for k in ("id", "sessionId", "branchId", "branchLabel", "historyCount")},
            "entries": [e for e in plan["entries"] if e["key"] in plan["range"]],
        }}

    def cancel(self, plan_id):
        with self.lock:
            plan = self.plans.get(plan_id)
            if plan and not plan["cancelled"]:
                if plan.get("started") and str(self.state.chat_session.get("sessionId")) == plan["sessionId"]:
                    self._send(plan, "replay-control", {"id": plan_id, "action": "stop"})
                plan["cancelled"] = True
        return {"ok": True}

    def is_active(self):
        sid = str(self.state.chat_session.get("sessionId") or "")
        with self.lock:
            return any(p.get("started") and not p["cancelled"] and p["sessionId"] == sid for p in self.plans.values())

    def _send(self, plan, command, payload):
        stream = getattr(self.state, "chat_stream", None)
        if not stream or not stream.send_command(plan["sessionId"], {"type": command, "payload": payload, "cmdId": uuid.uuid4().hex}):
            raise ValueError("聊天队列未连接，无法回放")

    def control(self, plan_id, body):
        plan = self._plan(plan_id)
        action = body.get("action")
        if action not in {"pause", "play", "seek", "skip-voice", "retry"} or not plan.get("started"):
            raise ValueError("回放操作无效")
        payload = {"id": plan_id, "action": action}
        if action == "seek":
            index = body.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(plan["selected"]):
                raise ValueError("位置不在回放片段内")
            payload.update(index=index, playing=body.get("playing") is True)
            plan["skipped"].discard(plan["selected"][index]["key"])
        if action == "skip-voice":
            *_, snapshot = self._context()
            progress = snapshot.get("replay") or {}
            if progress.get("id") == plan_id:
                plan["skipped"].add(plan["selected"][progress["index"]]["key"])
        if action == "retry":
            _, _, _, _, snapshot = self._context()
            progress = snapshot.get("replay") or {}
            if progress.get("id") == plan_id:
                key = plan["selected"][progress["index"]]["key"]
                plan["failures"].discard(key)
            return {"ok": True}
        self._send(plan, "replay-control", payload)
        return {"ok": True}

    def _prefetch(self, plan):
        while not plan["cancelled"]:
            try:
                self._plan(plan["id"])
                *_, snapshot = self._context()
                progress = snapshot.get("replay") or {}
                if progress.get("id") != plan["id"] or progress.get("paused") or progress.get("ended"):
                    time.sleep(0.1)
                    continue
                start = progress["index"]
                for entry in plan["selected"][start:start + 3]:
                    key = entry["key"]
                    if plan["cancelled"]:
                        return
                    if not entry["canGenerate"] or plan["private"][key]["paths"] or key in plan["failures"] or key in plan["skipped"]:
                        continue
                    try:
                        voice = self.generate(plan["id"], key)
                        paths = [str(p) for p in plan["private"][key]["paths"]]
                        self._plan(plan["id"])
                        self._send(plan, "replay-voice", {"id": plan["id"], "key": key, "paths": paths,
                            "voiceSource": voice["voiceSource"], "voiceLabel": voice["voiceLabel"]})
                    except Exception as exc:
                        if plan["cancelled"]:
                            return
                        plan["failures"].add(key)
                        self._send(plan, "replay-voice", {"id": plan["id"], "key": key, "error": str(exc)})
                    # Re-read the current queue position before choosing more work.
                    break
                time.sleep(0.05)
            except (ValueError, OSError):
                return

    def audio_source(self, plan_id, key, index):
        plan = self._plan(plan_id)
        if key not in (plan["range"] or set()):
            raise ValueError("音频不在回放范围内")
        paths = plan["private"][key]["paths"]
        if not 0 <= index < len(paths):
            raise ValueError("语音片段不存在")
        return paths[index]

    def generate(self, plan_id, key):
        plan = self._plan(plan_id)
        if not plan["generate"] or key not in (plan["range"] or set()):
            raise ValueError("未启用此片段的语音补全")
        entry = next(e for e in plan["entries"] if e["key"] == key)
        if not entry["canGenerate"]:
            raise ValueError("此记录没有可用的角色配音配置")
        # One request at a time; prefetch schedules only the current + next two
        # lines. Recheck cancellation after acquiring the shared model lock.
        with self.synthesis_lock:
            self._plan(plan_id)
            private = plan["private"][key]
            if private["paths"] and all(p.is_file() for p in private["paths"]):
                return {k: entry[k] for k in ("voiceUrls", "voiceSource", "voiceLabel")}
            store = plan["store"]
            character = private["character"]
            file_key = digest([key, private["speech"], plan["settings"], vars(character)])
            target = store.path(file_key, "wav")
            if not target.is_file():
                generated = self._synthesize(plan, entry, character)
                try:
                    # Cancellation prevents playback, but a completed result can
                    # be retained. A replaced/deleted conversation cannot be revived.
                    self._plan(plan_id, allow_cancelled=True)
                    store.directory.mkdir(parents=True, exist_ok=True)
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=store.directory, prefix=".replay-", suffix=".tmp", delete=False) as stream:
                            temporary = Path(stream.name)
                        shutil.copyfile(generated, temporary)
                        os.replace(temporary, target)
                    finally:
                        if temporary:
                            temporary.unlink(missing_ok=True)
                finally:
                    generated.unlink(missing_ok=True)
            store.write(key, "voice.json", {"fileKey": file_key, "speechKey": digest(private["speech"]),
                                            "label": entry["voiceLabel"], "source": "generated"})
            private["paths"] = [target]
            entry.update(voiceUrls=self._urls(plan_id, key, [target]), voiceSource="generated")
            return {k: entry[k] for k in ("voiceUrls", "voiceSource", "voiceLabel")}

    def _synthesize(self, plan, entry, character):
        from ai.llm.text_processor import TextProcessor
        from ai.tts.model_session import tts_model_session
        from ai.tts.tts_manager import TTSAdapterFactory, TTSManager
        settings = plan["settings"]
        manager = TTSManager(audio_cache_dir=Path(self.state.project_root_dir) / "cache" / "audio", unique_cache_files=True)
        try:
            adapter = TTSAdapterFactory.create_adapter(settings["provider"], **settings["kwargs"])
            manager.set_tts_adapter(adapter)
            adapter.wait_until_ready(timeout_seconds=30)
            processor = TextProcessor(pronunciation_map={})
            source = plan["private"][entry["key"]]["speech"]
            speech = processor.html_to_plain_qt(processor.remove_parentheses(source)).strip()
            if not speech:
                raise ValueError("此句只有动作描述，没有可合成的台词")
            # Read the saved line in its own language. Replay never asks a
            # translation service to rewrite the historical dialogue.
            manager.set_language(processor.decide_language(speech))
            def absolute(value):
                if not value or str(value).startswith("/kaggle/"):
                    return value or ""
                p = Path(value)
                return str(p if p.is_absolute() else Path(self.state.project_root_dir) / p)
            with tts_model_session(adapter, settings["url"]):
                self._plan(plan["id"])
                manager.switch_model({"character_name": entry["speaker"],
                                      "gpt_model_path": absolute(character.gpt_model_path),
                                      "sovits_model_path": absolute(character.sovits_model_path)})
                path = manager.generate_tts(speech, ref_audio_path=absolute(character.refer_audio_path),
                                            prompt_text=character.prompt_text, prompt_lang=character.prompt_lang,
                                            character_name=entry["speaker"], speed_factor=character.speech_speed)
            if not path or not Path(path).is_file():
                raise ValueError("语音生成失败，可重试或跳过本句语音")
            return Path(path)
        finally:
            manager.shutdown(stop_server=False)


_service_lock = threading.Lock()


def replay_service(state):
    with _service_lock:
        service = getattr(state, "chat_replay_service", None)
        if service is None:
            service = ChatReplayService(state)
            state.chat_replay_service = service
        return service
