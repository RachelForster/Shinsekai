"""Controlled Scene LLM loop with deterministic story-tool adjudication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
from types import MappingProxyType
from typing import Any, Protocol

from ai.tools.story_tools import (
    openai_tools_from_protocol,
    scene_tool_protocol_definitions,
)
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from core.story import (
    ApplySemanticSignals,
    CastResolutionContext,
    ConditionEvaluator,
    PerformIntent,
    RequestCharacterEntry,
    RequestCharacterExit,
    RequestCharacterReplace,
    SemanticSignalCandidate,
    SemanticSignalContext,
    SignalStrength,
    SpeechAct,
    StoryProgram,
)

from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    CHOICE_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    normalize_character_name,
)

from .characters import ActorContext, CharacterProfile, StoryCastApplicationService
from .idempotency import StoryCommandConflictError
from .prompt import (
    compose_story_chat_system_prompt,
    compose_story_system_prompt,
    compose_story_user_message,
    compose_story_user_scene_context,
)
from .session import (
    SceneTurnCommand,
    SceneTurnScope,
    StorySession,
    StoryTurnCancelledError,
)


MAX_SCENE_TOOL_ROUNDS = 6
MAX_SCENE_TOOL_CALLS = 12
MAX_DIALOGUE_ITEMS = 32
MAX_DIALOGUE_TEXT_CHARS = 4000
_NATIVE_TOOL_ADAPTERS = frozenset(
    {"DeepSeekAdapter", "OpenAIAdapter", "ClaudeAdapter"}
)
_DIALOG_SYSTEM_SPEAKERS = (
    NARR_ALIASES
    | CHOICE_ALIASES
    | STAT_ALIASES
    | SCENE_ALIASES
    | BGM_ALIASES
    | CG_ALIASES
    | COT_ALIASES
    | frozenset({"SYSTEM", "system"})
)


class SceneProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SceneModelPort(Protocol):
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SceneDialogueItem:
    character_id: str
    text: str
    emotion: str = ""
    sprite: str = ""
    effect: str = ""
    display_name: str = ""
    sprite_path: str = ""
    sprite_scale: float = 1.0
    color: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "characterId": self.character_id,
            "text": self.text,
        }
        if self.emotion:
            payload["emotion"] = self.emotion
        if self.sprite:
            payload["sprite"] = self.sprite
        if self.effect:
            payload["effect"] = self.effect
        if self.display_name:
            payload["displayName"] = self.display_name
        if self.sprite_path:
            payload["spritePath"] = self.sprite_path
        if self.sprite_scale != 1.0:
            payload["spriteScale"] = self.sprite_scale
        if self.color:
            payload["color"] = self.color
        return payload


@dataclass(frozen=True, slots=True)
class SceneTurnResult:
    command_id: str
    revision: int
    dialogue: tuple[SceneDialogueItem, ...]
    tool_results: tuple[Mapping[str, Any], ...]
    degraded: bool = False
    diagnostic: str = ""
    duplicate: bool = False
    presentation_events: tuple[Mapping[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "commandId": self.command_id,
            "revision": self.revision,
            "dialogue": [item.to_payload() for item in self.dialogue],
            "toolResults": [dict(item) for item in self.tool_results],
            "degraded": self.degraded,
            "diagnostic": self.diagnostic,
            "duplicate": self.duplicate,
            "presentationEvents": [dict(item) for item in self.presentation_events],
        }

    @classmethod
    def from_payload(
        cls,
        raw: Mapping[str, Any],
        *,
        duplicate: bool = False,
    ) -> SceneTurnResult:
        dialogue_raw = raw.get("dialogue")
        tool_results_raw = raw.get("toolResults")
        events_raw = raw.get("presentationEvents")
        if not isinstance(dialogue_raw, Sequence) or isinstance(
            dialogue_raw, (str, bytes, bytearray)
        ):
            raise SceneProtocolError("scene.turn_payload", "stored scene turn is invalid")
        if not isinstance(tool_results_raw, Sequence) or isinstance(
            tool_results_raw, (str, bytes, bytearray)
        ):
            tool_results_raw = ()
        if not isinstance(events_raw, Sequence) or isinstance(
            events_raw, (str, bytes, bytearray)
        ):
            events_raw = ()
        dialogue = []
        for item in dialogue_raw:
            if not isinstance(item, Mapping):
                continue
            dialogue.append(
                SceneDialogueItem(
                    character_id=str(item.get("characterId") or ""),
                    text=str(item.get("text") or ""),
                    emotion=str(item.get("emotion") or ""),
                    sprite=str(item.get("sprite") or ""),
                    effect=str(item.get("effect") or ""),
                    display_name=str(item.get("displayName") or ""),
                    sprite_path=str(item.get("spritePath") or ""),
                    sprite_scale=_sprite_scale_value(item.get("spriteScale")),
                    color=str(item.get("color") or ""),
                )
            )
        return cls(
            command_id=str(raw.get("commandId") or ""),
            revision=int(raw.get("revision") or 0),
            dialogue=tuple(dialogue),
            tool_results=tuple(
                MappingProxyType(dict(item))
                for item in tool_results_raw
                if isinstance(item, Mapping)
            ),
            degraded=bool(raw.get("degraded")),
            diagnostic=str(raw.get("diagnostic") or ""),
            duplicate=duplicate,
            presentation_events=tuple(
                MappingProxyType(dict(item))
                for item in events_raw
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorContext:
    """Compiler-only material that must never cross the scene-model firewall."""

    requirements: Mapping[str, Any]
    story_bible: Mapping[str, Any]
    hidden_constraints: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CastSelectionContext:
    candidate_ids: tuple[str, ...]
    required_ids: tuple[str, ...]
    maximum_active: int
    public_reasons: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SceneContexts:
    scene_understanding: Mapping[str, Any]
    actor: Mapping[str, Any]
    tools: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class StoryLlmTurn:
    """Scene judgment plus prompts for the chat before_chat hook."""

    appendix: str
    user_context: str
    system_prompt: str
    node_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class _ToolRecord:
    payload_hash: str
    result: Mapping[str, Any]


class ConfigSceneModel:
    """Lazy adapter from the existing configured LLM to the scene JSON protocol."""

    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        config_manager: Any,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.config_manager = config_manager
        self._manager: Any = None
        self._signature: tuple[tuple[str, str], ...] = ()

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        manager = self._llm_manager()
        protocol_tools = request.get("tools")
        if not isinstance(protocol_tools, Sequence) or isinstance(
            protocol_tools, (str, bytes, bytearray)
        ):
            protocol_tools = ()
        openai_tools = openai_tools_from_protocol(protocol_tools)
        adapter = getattr(manager, "llm_adapter", None)
        adapter_name = type(adapter).__name__
        messages = [
            {"role": "system", "content": compose_story_system_prompt(request)},
            {"role": "user", "content": compose_story_user_message(request)},
        ]
        chat_kwargs: dict[str, Any] = {}
        native_tools = bool(
            openai_tools and adapter_name in _NATIVE_TOOL_ADAPTERS
        )
        if native_tools:
            chat_kwargs["tools"] = openai_tools
        if adapter is None or not hasattr(adapter, "chat"):
            raise SceneProtocolError(
                "scene.model_not_configured",
                "scene LLM adapter is missing",
            )
        response = adapter.chat(messages, stream=False, **chat_kwargs)
        if response is None:
            raise SceneProtocolError(
                "scene.model_json",
                "scene model did not return a response",
            )
        if native_tools:
            return _parse_adapter_scene_response(response)
        return _parse_json_mapping(_adapter_text_content(response))

    def _llm_manager(self) -> Any:
        provider, model, base_url, api_key = self.config_manager.get_llm_api_config()
        if not provider or not model or not api_key:
            raise SceneProtocolError(
                "scene.model_not_configured",
                "scene LLM provider, model, or API key is missing",
            )
        factory_kwargs = self.config_manager.merged_llm_factory_kwargs(
            provider,
            {
                "llm_provider": provider,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            },
        )
        signature = tuple(
            sorted((str(key), repr(value)) for key, value in factory_kwargs.items())
        )
        if self._manager is None or signature != self._signature:
            from ai.llm.llm_manager import LLMAdapterFactory, LLMManager

            adapter = LLMAdapterFactory.create_adapter(**factory_kwargs)
            self._manager = LLMManager(
                adapter=adapter,
                user_template="",
            )
            self._signature = signature
        return self._manager


class SceneContextBuilder:
    def __init__(self, flags: FeatureFlagConfigManager) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags

    def build(
        self,
        program: StoryProgram,
        session: StorySession,
        actor_context: ActorContext,
        *,
        user_text: str,
        message_id: str,
    ) -> SceneContexts:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        state = session.active_branch.state
        node = program.nodes_by_id[state.current_node_id]
        variables = {
            **session.global_progress.variables,
            **state.variables,
        }
        evaluator = ConditionEvaluator()
        intents = [
            {"id": intent.id, "examples": list(intent.examples)}
            for intent in node.freeform_intents
            if evaluator.evaluate(
                intent.when,
                variables=variables,
                completed_node_ids=state.completed_node_ids,
            )
        ]
        scene_context = MappingProxyType(
            {
                "storyId": program.story_id,
                "storyVersion": program.story_version,
                "nodeId": node.id,
                "nodeTitle": node.title,
                "revision": state.revision,
                "publicContext": _protocol_value(node.exposed_context),
                "completedNodeIds": sorted(state.completed_node_ids),
                "canon": [fact.text for fact in state.canon],
                "visibleVariables": {
                    definition.id: _protocol_value(variables[definition.id])
                    for definition in program.variables
                    if definition.visible
                },
                "availableIntentIds": intents,
                "publishedSignalIds": [
                    definition.id for definition in program.semantic_signals
                ],
                "userInput": {"messageId": message_id, "text": user_text},
            }
        )
        actor = MappingProxyType(
            {
                "speakerAllowlist": list(actor_context.speaker_allowlist),
                "characters": [
                    {
                        "id": character_id,
                        "name": profile.name,
                        "setting": profile.setting,
                        "color": profile.color,
                        "isPlayer": profile.is_player,
                        "toolPermissions": list(profile.tool_permissions),
                        "sprites": () if profile.is_player else _sprite_summaries(profile),
                    }
                    for character_id, profile in actor_context.profiles.items()
                ],
            }
        )
        return SceneContexts(
            scene_understanding=scene_context,
            actor=actor,
            tools=scene_tool_protocol_definitions(
                program,
                node.id,
                state.revision,
                node.exposed_context,
                allowed_intent_ids=tuple(item["id"] for item in intents),
                allowed_character_ids_by_action=_character_tool_allowlists(
                    program,
                    session,
                    node,
                ),
            ),
        )


class ValidatedCastPlanner:
    """Accept model proposals only inside a deterministic candidate envelope."""

    def __init__(self, flags: FeatureFlagConfigManager) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags

    def validate(
        self,
        proposal: Sequence[str],
        *,
        candidate_ids: Sequence[str],
        required_ids: Sequence[str] = (),
        maximum_active: int,
    ) -> tuple[str, ...]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        candidates = set(candidate_ids)
        proposed = tuple(dict.fromkeys(str(item) for item in proposal))
        if not set(proposed).issubset(candidates):
            raise SceneProtocolError(
                "scene.cast_proposal_id",
                "cast proposal contains an ineligible character ID",
            )
        combined = tuple(dict.fromkeys((*required_ids, *proposed)))
        if len(combined) > maximum_active:
            raise SceneProtocolError(
                "scene.cast_proposal_size",
                "cast proposal exceeds maxActive",
            )
        return combined


class SceneOrchestrator:
    """Run a bounded proposal loop; only StorySession may mutate story state."""

    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        *,
        program: StoryProgram,
        session: StorySession,
        cast_service: StoryCastApplicationService,
        model: SceneModelPort,
        context_builder: SceneContextBuilder | None = None,
        max_rounds: int = MAX_SCENE_TOOL_ROUNDS,
        max_tool_calls: int = MAX_SCENE_TOOL_CALLS,
        repair_attempts: int = 1,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.program = program
        self.session = session
        self.cast_service = cast_service
        self.model = model
        self.context_builder = context_builder or SceneContextBuilder(flags)
        self.max_rounds = max(1, min(MAX_SCENE_TOOL_ROUNDS, int(max_rounds)))
        self.max_tool_calls = max(1, min(MAX_SCENE_TOOL_CALLS, int(max_tool_calls)))
        self.repair_attempts = max(0, min(2, int(repair_attempts)))
        self._tool_records: dict[str, _ToolRecord] = {}
        self._scope: SceneTurnScope | None = None
        self._presentation_events: list[Mapping[str, Any]] = []

    def prepare_llm_turn(
        self,
        text: str,
        *,
        command_id: str,
        message_id: str,
    ) -> StoryLlmTurn:
        """Judge the current scene and return a prompt appendix. No presentation LLM."""
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        user_text = str(text or "").strip()
        actor_context = self.cast_service.resources.actor_context()
        contexts = self.context_builder.build(
            self.program,
            self.session,
            actor_context,
            user_text=user_text,
            message_id=message_id,
        )
        request = self._request_payload(
            contexts,
            command_id=command_id,
            round_index=0,
            tool_results=(),
        )
        user_context = compose_story_user_scene_context(request)
        system_prompt = compose_story_chat_system_prompt(request)
        state = self.session.active_branch.state
        return StoryLlmTurn(
            appendix=user_context,
            user_context=user_context,
            system_prompt=system_prompt,
            node_id=state.current_node_id,
            revision=state.revision,
        )

    def handle_free_text(
        self,
        text: str,
        *,
        command_id: str,
        message_id: str,
    ) -> SceneTurnResult:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        user_text = str(text).strip()
        if not user_text:
            raise ValueError("scene input cannot be empty")
        command = SceneTurnCommand(
            command_id=command_id,
            message_id=message_id,
            text=user_text,
        )
        try:
            existing = self.session.lookup_recorded_command(command)
        except StoryCommandConflictError as error:
            raise SceneProtocolError(
                "scene.command_id_conflict",
                "scene command ID was reused with different input",
            ) from error
        if existing is not None:
            payload = existing.ack.get("sceneTurn")
            if not isinstance(payload, Mapping):
                raise SceneProtocolError(
                    "scene.turn_payload",
                    "stored scene turn is invalid",
                )
            return SceneTurnResult.from_payload(payload, duplicate=True)
        scope = self.session.begin_scene_turn()
        self._scope = scope
        self._presentation_events = []
        actor_context = self.cast_service.resources.actor_context()
        contexts = self.context_builder.build(
            self.program,
            self.session,
            actor_context,
            user_text=user_text,
            message_id=message_id,
        )
        tool_results: list[Mapping[str, Any]] = []
        total_calls = 0
        try:
            for round_index in range(self.max_rounds):
                self._require_active_scope()
                request = self._request_payload(
                    contexts,
                    command_id=command_id,
                    round_index=round_index,
                    tool_results=tool_results,
                )
                response = self.model.complete(request)
                self._require_active_scope()
                raw_calls = response.get("toolCalls")
                if (
                    isinstance(raw_calls, Sequence)
                    and not isinstance(raw_calls, (str, bytes, bytearray))
                    and raw_calls
                ):
                    if total_calls + len(raw_calls) > self.max_tool_calls:
                        raise SceneProtocolError(
                            "scene.tool_limit",
                            "scene model exceeded the tool-call limit",
                        )
                    for raw_call in raw_calls:
                        result = self._execute_tool_call(
                            raw_call,
                            turn_command_id=command_id,
                            message_id=message_id,
                        )
                        tool_results.append(MappingProxyType(result))
                        total_calls += 1
                    actor_context = self.cast_service.resources.actor_context()
                    contexts = self.context_builder.build(
                        self.program,
                        self.session,
                        actor_context,
                        user_text=user_text,
                        message_id=message_id,
                    )
                    continue
                dialogue = self._validated_dialogue(response, actor_context)
                return self._persist_turn(
                    command,
                    SceneTurnResult(
                        command_id=command_id,
                        revision=self.session.active_branch.state.revision,
                        dialogue=dialogue,
                        tool_results=tuple(tool_results),
                        presentation_events=tuple(self._presentation_events),
                    ),
                )
            raise SceneProtocolError(
                "scene.round_limit",
                "scene model did not finish within the bounded tool loop",
            )
        except StoryTurnCancelledError:
            raise
        except Exception as error:
            if isinstance(error, SceneProtocolError) and error.code.startswith(
                "scene.dialogue_"
            ):
                repaired = self._repair_dialogue(
                    contexts,
                    actor_context,
                    command_id=command_id,
                    tool_results=tool_results,
                    error=error,
                )
                if repaired is not None:
                    return self._persist_turn(
                        command,
                        SceneTurnResult(
                            command_id=command_id,
                            revision=self.session.active_branch.state.revision,
                            dialogue=repaired,
                            tool_results=tuple(tool_results),
                            diagnostic=error.code,
                            presentation_events=tuple(self._presentation_events),
                        ),
                    )
            return self._persist_turn(
                command,
                self._fallback(
                    command_id,
                    tool_results,
                    getattr(error, "code", type(error).__name__),
                ),
            )
        finally:
            self.session.end_scene_turn(scope)
            self._scope = None

    def _require_active_scope(self) -> None:
        scope = self._scope
        if scope is None:
            raise StoryTurnCancelledError(
                "scene.session_invalid",
                "scene turn is no longer bound to this session",
            )
        self._scope = self.session.validate_scene_scope(scope)

    def _persist_turn(
        self,
        command: SceneTurnCommand,
        result: SceneTurnResult,
    ) -> SceneTurnResult:
        ack = self.session.record_scene_turn(
            command,
            result_payload=result.to_payload(),
            scene_scope=self._scope,
        )
        payload = ack.get("sceneTurn")
        if isinstance(payload, Mapping):
            return SceneTurnResult.from_payload(payload, duplicate=result.duplicate)
        return result

    def _execute_story_command(self, command: Any) -> Any:
        self._require_active_scope()
        ack = self.session.execute(command, scene_scope=self._scope)
        if self._scope is not None:
            self._scope = replace(self._scope, generation=ack.generation)
        self._presentation_events.extend(ack.presentation_events)
        return ack

    def _execute_tool_call(
        self,
        raw_call: Any,
        *,
        turn_command_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        if not isinstance(raw_call, Mapping):
            raise SceneProtocolError(
                "scene.tool_schema",
                "tool call must be an object",
            )
        tool_call_id = str(raw_call.get("id") or "").strip()
        name = str(raw_call.get("name") or "").strip()
        arguments = raw_call.get("arguments")
        if not tool_call_id or not name or not isinstance(arguments, Mapping):
            raise SceneProtocolError(
                "scene.tool_schema",
                "tool call id, name, and arguments are required",
            )
        record_key = f"{turn_command_id}:{tool_call_id}"
        payload_hash = hashlib.sha256(
            json.dumps(
                {"name": name, "arguments": _protocol_value(arguments)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        existing = self._tool_records.get(record_key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise SceneProtocolError(
                    "scene.tool_id_conflict",
                    "tool-call ID was reused with different arguments",
                )
            return {**dict(existing.result), "duplicate": True}
        try:
            result = self._dispatch_tool(
                name,
                arguments,
                command_id=record_key,
                message_id=message_id,
            )
        except Exception as error:
            result = {
                "toolCallId": tool_call_id,
                "name": name,
                "ok": False,
                "errorCode": getattr(error, "code", type(error).__name__),
                "error": str(error)[:500],
            }
        frozen = MappingProxyType(result)
        self._tool_records[record_key] = _ToolRecord(payload_hash, frozen)
        while len(self._tool_records) > 512:
            self._tool_records.pop(next(iter(self._tool_records)))
        return dict(result)

    def _dispatch_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        command_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        state = self.session.active_branch.state
        expected_node_id, expected_revision = _request_boundary(arguments)
        if name == "perform_intent":
            ack = self._execute_story_command(
                PerformIntent(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    intent_id=str(arguments.get("intentId") or ""),
                    expected_node_id=expected_node_id,
                )
            )
        elif name == "apply_semantic_signal":
            signal_id = str(arguments.get("signalId") or "")
            if signal_id not in self.program.semantic_signals_by_id:
                raise SceneProtocolError(
                    "scene.signal_id",
                    "semantic signal ID is not published",
                )
            strength = SignalStrength(str(arguments.get("strength") or ""))
            speech_act = SpeechAct(str(arguments.get("speechAct") or ""))
            confidence = float(arguments.get("confidence"))
            fingerprint = hashlib.sha256(
                f"{signal_id}\0{message_id}".encode("utf-8")
            ).hexdigest()
            ack = self._execute_story_command(
                ApplySemanticSignals(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    candidates=(
                        SemanticSignalCandidate(
                            signal_id=signal_id,
                            strength=strength,
                            confidence=confidence,
                            speech_act=speech_act,
                            fingerprint=fingerprint,
                            source_message_id=message_id,
                            cause_group=f"{message_id}:{signal_id}",
                        ),
                    ),
                    context=SemanticSignalContext(
                        turn_id=message_id,
                        scene_id=state.current_node_id,
                        chapter_id=f"story:{self.program.story_version}",
                    ),
                )
            )
        elif name == "request_character_entry":
            ack = self._execute_story_command(
                RequestCharacterEntry(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    character_id=str(arguments.get("characterId") or ""),
                    reason_id=str(arguments.get("reasonId") or ""),
                    expected_node_id=expected_node_id,
                )
            )
        elif name == "request_character_exit":
            ack = self._execute_story_command(
                RequestCharacterExit(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    character_id=str(arguments.get("characterId") or ""),
                    reason_id=str(arguments.get("reasonId") or ""),
                    expected_node_id=expected_node_id,
                )
            )
        elif name == "request_character_replace":
            ack = self._execute_story_command(
                RequestCharacterReplace(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    outgoing_character_id=str(
                        arguments.get("outgoingCharacterId") or ""
                    ),
                    incoming_character_id=str(
                        arguments.get("incomingCharacterId") or ""
                    ),
                    reason_id=str(arguments.get("reasonId") or ""),
                    expected_node_id=expected_node_id,
                )
            )
        else:
            raise SceneProtocolError(
                "scene.tool_name",
                f"tool {name!r} is not available",
            )
        return {
            "toolCallId": command_id.rpartition(":")[2],
            "name": name,
            "ok": True,
            "revision": ack.revision,
            "eventIds": list(ack.event_ids),
        }

    def _validated_dialogue(
        self,
        response: Mapping[str, Any],
        actor_context: ActorContext,
    ) -> tuple[SceneDialogueItem, ...]:
        raw_dialogue = _raw_dialogue_items(response)
        if not isinstance(raw_dialogue, Sequence) or isinstance(
            raw_dialogue, (str, bytes, bytearray)
        ):
            raise SceneProtocolError(
                "scene.dialogue_schema",
                "dialogue must be a list",
            )
        if not raw_dialogue or len(raw_dialogue) > MAX_DIALOGUE_ITEMS:
            raise SceneProtocolError(
                "scene.dialogue_size",
                "dialogue item count is invalid",
            )
        dialogue = []
        for raw_item in raw_dialogue:
            if not isinstance(raw_item, Mapping):
                raise SceneProtocolError(
                    "scene.dialogue_schema",
                    "dialogue item must be an object",
                )
            item = _dialogue_item_from_mapping(raw_item, actor_context)
            profile = actor_context.profiles.get(item.character_id)
            if profile is not None and profile.is_player:
                continue
            if len(item.text) > MAX_DIALOGUE_TEXT_CHARS:
                raise SceneProtocolError(
                    "scene.dialogue_text",
                    "dialogue text is empty or too long",
                )
            if not item.text and item.character_id not in _DIALOG_SYSTEM_SPEAKERS:
                raise SceneProtocolError(
                    "scene.dialogue_text",
                    "dialogue text is empty or too long",
                )
            dialogue.append(item)
        if not dialogue:
            raise SceneProtocolError(
                "scene.dialogue_player",
                "do not speak as the player; player lines come from player input",
            )
        return tuple(dialogue)

    def _repair_dialogue(
        self,
        contexts: SceneContexts,
        actor_context: ActorContext,
        *,
        command_id: str,
        tool_results: Sequence[Mapping[str, Any]],
        error: SceneProtocolError,
    ) -> tuple[SceneDialogueItem, ...] | None:
        for attempt in range(self.repair_attempts):
            try:
                response = self.model.complete(
                    {
                        **self._request_payload(
                            contexts,
                            command_id=command_id,
                            round_index=self.max_rounds + attempt,
                            tool_results=tool_results,
                        ),
                        "mode": "repair-dialogue",
                        "validationError": {
                            "code": error.code,
                            "message": str(error),
                        },
                        "tools": [],
                    }
                )
                return self._validated_dialogue(response, actor_context)
            except Exception:
                continue
        return None

    def _request_payload(
        self,
        contexts: SceneContexts,
        *,
        command_id: str,
        round_index: int,
        tool_results: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "protocol": "shinsekai.scene.v1",
            "commandId": command_id,
            "round": round_index,
            "scene": dict(contexts.scene_understanding),
            "actorContext": dict(contexts.actor),
            "tools": [dict(item) for item in contexts.tools],
            "toolResults": [dict(item) for item in tool_results],
        }

    def _fallback(
        self,
        command_id: str,
        tool_results: Sequence[Mapping[str, Any]],
        diagnostic: str,
    ) -> SceneTurnResult:
        node = self.program.nodes_by_id[
            self.session.active_branch.state.current_node_id
        ]
        return SceneTurnResult(
            command_id=command_id,
            revision=self.session.active_branch.state.revision,
            dialogue=(
                SceneDialogueItem(
                    character_id="NARR",
                    text=f"场景暂时停在「{node.title}」。",
                ),
            ),
            tool_results=tuple(tool_results),
            degraded=True,
            diagnostic=str(diagnostic),
            presentation_events=tuple(self._presentation_events),
        )


def _character_tool_allowlists(
    program: StoryProgram,
    session: StorySession,
    node: Any,
) -> dict[str, tuple[str, ...]]:
    state = session.active_branch.state
    active = tuple(state.cast_state.active_character_ids)
    context = CastResolutionContext(current_cast=active)
    entry_ids = session.runtime.cast_resolver.optional_candidate_ids(
        program.character_registry,
        node.cast_policy,
        context,
        exclude_ids=active,
    )
    protected = set(node.cast_policy.required) | set(
        state.cast_state.role_bindings.values()
    )
    exit_ids = tuple(
        character_id for character_id in active if character_id not in protected
    )
    return {
        "entry": entry_ids,
        "exit": exit_ids,
        "replace": tuple(dict.fromkeys((*exit_ids, *entry_ids))),
    }


def _parse_adapter_scene_response(response: Any) -> Mapping[str, Any]:
    native_calls = _native_tool_calls(response)
    if native_calls:
        return {"toolCalls": native_calls}
    return _parse_json_mapping(_adapter_text_content(response))


def _native_tool_calls(response: Any) -> list[dict[str, Any]]:
    content = getattr(response, "content", None)
    if isinstance(content, list):
        calls: list[dict[str, Any]] = []
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type is None and isinstance(block, Mapping):
                block_type = block.get("type")
            if block_type != "tool_use":
                continue
            if isinstance(block, Mapping):
                calls.append(
                    {
                        "id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                        "arguments": _as_argument_mapping(block.get("input")),
                    }
                )
                continue
            calls.append(
                {
                    "id": str(getattr(block, "id", "") or ""),
                    "name": str(getattr(block, "name", "") or ""),
                    "arguments": _as_argument_mapping(getattr(block, "input", None)),
                }
            )
        if calls:
            return calls
    choices = getattr(response, "choices", None)
    if not choices:
        return []
    message = choices[0].message
    raw_calls = getattr(message, "tool_calls", None) or []
    parsed: list[dict[str, Any]] = []
    for tool_call in raw_calls:
        function = getattr(tool_call, "function", None)
        if function is not None:
            name = getattr(function, "name", "")
            arguments = getattr(function, "arguments", {})
        else:
            name = getattr(tool_call, "name", "")
            arguments = getattr(tool_call, "input", {})
        parsed.append(
            {
                "id": str(getattr(tool_call, "id", "") or ""),
                "name": str(name or ""),
                "arguments": _as_argument_mapping(arguments),
            }
        )
    return parsed


def _adapter_text_content(response: Any) -> Any:
    if isinstance(response, (str, Mapping)):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if getattr(block, "type", None) == "text":
                texts.append(getattr(block, "text", "") or "")
            elif isinstance(block, Mapping) and block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
        if texts:
            return "".join(texts)
    choices = getattr(response, "choices", None)
    if choices:
        return getattr(choices[0].message, "content", None) or ""
    return response


def _as_argument_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return dict(parsed)
    return {}


def _request_boundary(arguments: Mapping[str, Any]) -> tuple[str, int]:
    node_id = str(arguments.get("expectedNodeId") or "").strip()
    try:
        revision = int(arguments.get("expectedRevision"))
    except (TypeError, ValueError) as error:
        raise SceneProtocolError(
            "scene.tool_revision",
            "tool expectedRevision is invalid",
        ) from error
    if not node_id:
        raise SceneProtocolError(
            "scene.tool_node",
            "tool expectedNodeId is empty",
        )
    return node_id, revision


def _parse_json_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise SceneProtocolError(
            "scene.model_json",
            "scene model did not return a JSON object",
        ) from error
    if not isinstance(parsed, Mapping):
        raise SceneProtocolError(
            "scene.model_schema",
            "scene model response must be an object",
        )
    return parsed


def _raw_dialogue_items(response: Mapping[str, Any]) -> Any:
    if "dialog" in response:
        return response.get("dialog")
    return response.get("dialogue")


def _dialogue_item_from_mapping(
    raw_item: Mapping[str, Any],
    actor_context: ActorContext,
) -> SceneDialogueItem:
    speaker_raw = str(
        raw_item.get("character_name")
        or raw_item.get("characterName")
        or raw_item.get("characterId")
        or ""
    ).strip()
    text = str(raw_item.get("speech") or raw_item.get("text") or "").strip()
    sprite_token = str(raw_item.get("sprite") or raw_item.get("emotion") or "").strip()
    character_id, profile = _resolve_speaker(speaker_raw, actor_context)
    display_name = profile.name if profile is not None else character_id
    if profile is not None and profile.is_player:
        sprite_path, sprite_scale = "", 1.0
    else:
        sprite_path, sprite_scale = _sprite_resource(profile, sprite_token)
    return SceneDialogueItem(
        character_id=character_id,
        text=text,
        emotion=str(raw_item.get("emotion") or "")[:100],
        sprite=sprite_token[:32],
        effect=str(raw_item.get("effect") or "")[:100],
        display_name=display_name,
        sprite_path=sprite_path,
        sprite_scale=sprite_scale,
        color=str(profile.color if profile is not None else ""),
    )


def _resolve_speaker(
    speaker: str,
    actor_context: ActorContext,
) -> tuple[str, CharacterProfile | None]:
    normalized = normalize_character_name(speaker)
    if normalized in _DIALOG_SYSTEM_SPEAKERS or speaker in _DIALOG_SYSTEM_SPEAKERS:
        return normalized or speaker, None
    from config.config_manager import character_name_key

    wanted = character_name_key(speaker)
    for character_id, profile in actor_context.profiles.items():
        if character_id == speaker or profile.name == speaker:
            return character_id, profile
        if character_name_key(character_id) == wanted:
            return character_id, profile
        if character_name_key(profile.name) == wanted:
            return character_id, profile
    allowed = set(actor_context.speaker_allowlist)
    if speaker in allowed or normalized in allowed:
        return speaker, None
    raise SceneProtocolError(
        "scene.dialogue_speaker",
        f"speaker {speaker!r} is not active",
    )


def _sprite_summaries(profile: CharacterProfile) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for index, sprite in enumerate(profile.sprites, start=1):
        if not isinstance(sprite, Mapping):
            continue
        label = str(
            sprite.get("label")
            or sprite.get("tag")
            or sprite.get("emotion")
            or sprite.get("emotion_tag")
            or ""
        ).strip()
        summaries.append({"id": f"{index:02d}", "label": label})
    return summaries


def _sprite_resource(
    profile: CharacterProfile | None,
    sprite_token: str,
) -> tuple[str, float]:
    if profile is None or not profile.sprites:
        return "", 1.0
    token = sprite_token.strip()
    if not token or token in {"-1", "0"}:
        sprite = profile.sprites[0]
        return str(sprite.get("path") or ""), _sprite_scale_value(sprite.get("scale"))
    try:
        index = int(token) - 1
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(profile.sprites):
        index = 0
    sprite = profile.sprites[index]
    return str(sprite.get("path") or ""), _sprite_scale_value(sprite.get("scale"))


def _sprite_scale_value(value: Any) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    if scale <= 0:
        return 1.0
    return scale


def _protocol_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _protocol_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(_protocol_value(item) for item in value)
    if isinstance(value, (tuple, list)):
        return [_protocol_value(item) for item in value]
    return value
