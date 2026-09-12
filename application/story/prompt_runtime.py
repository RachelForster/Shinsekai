"""Story progression layered onto the ordinary template chat via existing hooks.

No scene dialogue, cast resources, rendering commands or output contracts live
here. The normal chat model produces its normal response; a separate assessment
of that response advances the saved node for the next prompt.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from ai.llm.template.core import TemplateContext
from ai.llm.template.story import (
    StoryGuidanceContext,
    StoryGuidanceTransition,
    StoryRequestContext,
    build_story_guidance_section,
    build_story_assessment_system_section,
    build_story_assessment_user_section,
)
from config.feature_flags import FeatureFlag
from core.chat_history.storage import chat_history_session_dir
from core.chat_history.text import parse_assistant_dialog_content
from core.story import AdvanceStoryTurn, StoryCompiler, StoryRuntime
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher
from sdk.path_utils import safe_existing_path
from .generation import _adapter_text_content, _parse_json_mapping
from .persistence import (
    JsonGlobalStoryProgressStore,
    JsonStorySessionRepository,
    StoryConcurrentWriteError,
    _atomic_write_json,
)
from .project_loader import load_story_project
from .session import StorySession
from .prompt_turns import PromptTurnJournal, assessment_message

BINDING_FILENAME = "story-prompt-binding.json"
logger = logging.getLogger(__name__)


def bind_story_prompt(
    history_path: str | Path, story_path: Path, project_root: Path, global_root: Path
) -> None:
    _atomic_write_json(
        chat_history_session_dir(history_path) / BINDING_FILENAME,
        {
            "storyPath": str(story_path),
            "projectRoot": str(project_root),
            "globalRoot": str(global_root),
        },
    )


def load_prompt_session(history_path: str | Path, flags: Any) -> StorySession | None:
    flags.require(FeatureFlag.STORY_SYSTEM)
    directory = chat_history_session_dir(history_path)
    binding = directory / BINDING_FILENAME
    if (
        not binding.is_file()
        or not JsonStorySessionRepository(directory).path.is_file()
    ):
        return None
    data = json.loads(binding.read_text(encoding="utf-8"))
    root = Path(data["projectRoot"]).resolve()
    story_path = safe_existing_path(
        data["storyPath"], roots=(root,), field="story path"
    )
    global_root = Path(data["globalRoot"]).resolve()
    if not global_root.is_relative_to(root):
        raise ValueError("story progress path escaped project root")
    program = StoryCompiler().compile(load_story_project(story_path))
    session = StorySession.recover(
        StoryRuntime(program),
        flags,
        repository=JsonStorySessionRepository(directory),
        global_store=JsonGlobalStoryProgressStore(global_root),
    )
    session.owner_history_path = str(Path(history_path).resolve())
    return session


def node_prompt(session: StorySession) -> str:
    state = session.active_branch.state
    node = session.runtime.program.nodes_by_id[state.current_node_id]
    context = StoryGuidanceContext(
        title=node.title,
        instruction=node.instruction,
        turn_count=state.node_turn_count,
        max_rounds=node.max_rounds,
        transitions=tuple(
            StoryGuidanceTransition(
                condition=item.when,
                next_title=session.runtime.program.nodes_by_id[item.to_node_id].title,
            )
            for item in node.transitions
        ),
        background=node.background,
    )
    return build_story_guidance_section().render(context)


class StoryPromptHooks:
    def __init__(self, history_path: str, flags: Any, adapter: Any) -> None:
        self.history_path = history_path
        self.flags = flags
        self.adapter = adapter
        self.publish = lambda story: None
        self.history_entries = lambda: []
        self.branch_id = lambda: None
        self.journal = PromptTurnJournal(history_path)
        self._turn: tuple[str, str, int, str] | None = None
        self._history: list[dict[str, Any]] = []
        self._assessment: list[dict[str, Any]] = []

    @staticmethod
    def _identity(session: StorySession) -> tuple[str, str, int, str]:
        return (
            session.active_branch_id,
            session.active_branch.state.current_node_id,
            session.active_branch.state.revision,
            session.repository.document_revision,
        )

    def before_chat(self, context: BeforeChatContext) -> None:
        if not self.flags.is_enabled(FeatureFlag.STORY_SYSTEM):
            return
        self._turn = None
        self.recover_pending()
        session = load_prompt_session(self.history_path, self.flags)
        if session is None:
            self._turn = None
            return
        if (
            self.branch_id() is not None
            and self.branch_id() != session.active_branch_id
        ):
            return
        self._turn = self._identity(session)
        # UI history is uncompressed and uses the same user order as fork/revert.
        self._history = copy.deepcopy(self.history_entries())
        self._assessment = [
            assessment_message(item)
            for item in context.messages
            if item.get("role") in {"user", "assistant"}
        ][-11:]
        # BEFORE_CHAT receives a copy, so the base template/history stay intact.
        context.messages.insert(
            1
            if context.messages and context.messages[0].get("role") == "system"
            else 0,
            {"role": "system", "content": node_prompt(session)},
        )

    def persist_message(self, message: dict[str, Any]) -> bool:
        """Journal accepted dialogue before the normal incremental history write."""
        if (
            self._turn is None
            or message.get("role") != "assistant"
            or message.get("tool_calls")
            or not parse_assistant_dialog_content(message.get("content"))
        ):
            return False
        if self.branch_id() is not None and self.branch_id() != self._turn[0]:
            return False
        message.setdefault("_storyTurnId", uuid.uuid4().hex)
        turn = {
            "expected": self._turn,
            "message": copy.deepcopy(message),
            "conversation": [*self._assessment, assessment_message(message)],
            "historyEntries": [*self._history, assessment_message(message)],
        }
        self.journal.save(turn)
        self.journal.ensure_reply(turn)
        return True

    def recover_pending(self) -> None:
        if not self.flags.is_enabled(FeatureFlag.STORY_SYSTEM):
            return
        turn = self.journal.load()
        if turn is None:
            return
        session = load_prompt_session(self.history_path, self.flags)
        if session is None or tuple(turn["expected"]) != self._identity(session):
            self.journal.clear()
            return
        self.journal.ensure_reply(turn)
        self._advance(turn)

    def message_added(self, context: MessageAddedContext) -> None:
        if (
            not self.flags.is_enabled(FeatureFlag.STORY_SYSTEM)
            or self._turn is None
            or context.role != "assistant"
            or context.message.get("tool_calls")
            or not parse_assistant_dialog_content(context.message.get("content"))
        ):
            return
        if self.journal.load() is None:
            self.persist_message(copy.deepcopy(context.message))
        self._turn = None
        self.recover_pending()

    def _advance(self, turn: dict[str, Any]) -> None:
        expected = tuple(turn["expected"])
        session = load_prompt_session(self.history_path, self.flags)
        if session is None:
            return
        state = session.active_branch.state
        if expected != self._identity(session):
            return  # The user rolled back/switched branches during generation.
        node = session.runtime.program.nodes_by_id[state.current_node_id]
        if node.type not in {"limited_turn_node", "free_chat_node"}:
            self.journal.clear()
            return
        messages = [
            assessment_message(item)
            for item in turn["conversation"]
            if item.get("role") in {"user", "assistant"}
        ]
        target = None
        if node.transitions:
            try:
                request = {
                    "currentNode": node.id,
                    "instruction": node.instruction,
                    "turnCount": state.node_turn_count + 1,
                    "transitions": [
                        {"nextNodeId": item.to_node_id, "condition": item.when}
                        for item in node.transitions
                    ],
                    "conversation": messages[-12:],
                }
                response = self.adapter.chat(
                    [
                        {
                            "role": "system",
                            "content": build_story_assessment_system_section().render(
                                TemplateContext()
                            ),
                        },
                        {
                            "role": "user",
                            "content": build_story_assessment_user_section().render(
                                StoryRequestContext(request)
                            ),
                        },
                    ],
                    stream=False,
                )
                target = _parse_json_mapping(_adapter_text_content(response)).get(
                    "nextNodeId"
                )
                if target not in {item.to_node_id for item in node.transitions}:
                    target = None
            except Exception:
                target = None
                logger.exception(
                    "Story state assessment failed; keeping normal dialogue and current progression"
                )
        # Never coerce a media choice or speaker. Only the deterministic node
        # transition is committed; normal dialogue has already been accepted.
        if (
            node.max_rounds
            and state.node_turn_count + 1 >= node.max_rounds
            and target is None
            and node.default_to is None
        ):
            self.journal.clear()
            return
        fresh = load_prompt_session(self.history_path, self.flags)
        if fresh is None or expected != self._identity(fresh):
            self.journal.clear()
            return
        try:
            fresh.execute(
                AdvanceStoryTurn(
                    command_id="template-turn:" + turn["message"]["_storyTurnId"],
                    expected_revision=state.revision,
                    expected_node_id=node.id,
                    next_node_id=target,
                ),
                history_entries=turn["historyEntries"],
            )
        except StoryConcurrentWriteError:
            self.journal.clear()
            return
        self.journal.clear()
        self.publish(fresh.chat_snapshot()["story"])


def install_story_prompt_hooks(
    llm_manager: Any, config: Any, history_path: str
) -> None:
    flags = getattr(config, "feature_flags", None)
    if not history_path or flags is None:
        return
    dispatcher = getattr(llm_manager, "hook_dispatcher", None)
    if dispatcher is None:
        dispatcher = PluginHookDispatcher()
        llm_manager.hook_dispatcher = dispatcher
    hooks = StoryPromptHooks(history_path, flags, llm_manager.llm_adapter)
    from application.chat.history_state import (
        get_history,
        serialize_chat_history_entries,
    )

    hooks.history_entries = lambda: serialize_chat_history_entries(list(get_history()))
    dispatcher.register_before_chat(hooks.before_chat, label="story_prompt")
    dispatcher.register_message_added(hooks.message_added, label="story_progress")
    llm_manager.story_prompt_hooks = hooks
