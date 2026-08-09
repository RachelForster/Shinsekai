"""Pure semantic-signal acceptance, deduplication, and quota policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import math
from types import MappingProxyType

from .models import EffectSpec
from .state import SemanticSignalState


class SignalStrength(str, Enum):
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class SpeechAct(str, Enum):
    ENDORSEMENT = "endorsement"
    ACTION = "action"
    QUESTION = "question"
    QUOTATION = "quotation"
    HYPOTHETICAL = "hypothetical"
    SARCASM = "sarcasm"


@dataclass(frozen=True, slots=True)
class SemanticSignalDefinition:
    id: str
    effects_by_strength: Mapping[SignalStrength, tuple[EffectSpec, ...]]
    minimum_confidence: float = 0.8
    allowed_speech_acts: frozenset[SpeechAct] = frozenset(
        {SpeechAct.ENDORSEMENT, SpeechAct.ACTION}
    )
    repeat_window: int = 20
    max_per_turn: int = 1
    max_per_scene: int = 3
    max_per_chapter: int = 10

    def __post_init__(self) -> None:
        effects = {
            SignalStrength(strength): tuple(items)
            for strength, items in self.effects_by_strength.items()
        }
        object.__setattr__(self, "effects_by_strength", MappingProxyType(effects))
        object.__setattr__(
            self,
            "allowed_speech_acts",
            frozenset(SpeechAct(item) for item in self.allowed_speech_acts),
        )


@dataclass(frozen=True, slots=True)
class SemanticSignalCandidate:
    signal_id: str
    strength: SignalStrength
    confidence: float
    speech_act: SpeechAct
    fingerprint: str
    source_message_id: str
    cause_group: str


@dataclass(frozen=True, slots=True)
class SemanticSignalContext:
    turn_id: str
    scene_id: str
    chapter_id: str
    suppressed_cause_groups: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SemanticSignalDecision:
    candidate: SemanticSignalCandidate
    accepted: bool
    reason_code: str
    effects: tuple[EffectSpec, ...] = ()
    metric_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticPolicyResult:
    state: SemanticSignalState
    decisions: tuple[SemanticSignalDecision, ...]


class SemanticSignalPolicy:
    def evaluate(
        self,
        state: SemanticSignalState,
        definitions: Mapping[str, SemanticSignalDefinition],
        candidates: tuple[SemanticSignalCandidate, ...],
        context: SemanticSignalContext,
    ) -> SemanticPolicyResult:
        sequence = state.sequence
        usage = dict(state.usage)
        turn_id = state.turn_id
        scene_id = state.scene_id
        chapter_id = state.chapter_id
        fingerprints = list(state.recent_fingerprints)
        cause_groups = list(state.accepted_cause_groups)
        decisions: list[SemanticSignalDecision] = []

        for candidate in candidates:
            definition = definitions.get(candidate.signal_id)
            metric_ids = self._metric_ids(definition, candidate.strength)
            scoped_usage = self._usage_for_context(
                usage,
                turn_id=turn_id,
                scene_id=scene_id,
                chapter_id=chapter_id,
                context=context,
            )
            reason = self._rejection_reason(
                candidate,
                definition,
                state_sequence=sequence,
                usage=scoped_usage,
                fingerprints=fingerprints,
                cause_groups=cause_groups,
                context=context,
                metric_ids=metric_ids,
            )
            if reason is not None or definition is None:
                decisions.append(
                    SemanticSignalDecision(
                        candidate=candidate,
                        accepted=False,
                        reason_code=reason or "unknown-signal",
                    )
                )
                continue

            sequence += 1
            usage = scoped_usage
            turn_id = context.turn_id
            scene_id = context.scene_id
            chapter_id = context.chapter_id
            fingerprint_key = f"{candidate.signal_id}:{candidate.fingerprint}"
            fingerprints.append((fingerprint_key, sequence))
            cause_groups.append(candidate.cause_group)
            for key in self._usage_keys(metric_ids):
                usage[key] = usage.get(key, 0) + 1
            effects = tuple(definition.effects_by_strength.get(candidate.strength, ()))
            decisions.append(
                SemanticSignalDecision(
                    candidate=candidate,
                    accepted=True,
                    reason_code="accepted",
                    effects=effects,
                    metric_ids=metric_ids,
                )
            )

        minimum_sequence = max(0, sequence - 256)
        fingerprints = [item for item in fingerprints if item[1] >= minimum_sequence][
            -256:
        ]
        cause_groups = cause_groups[-256:]
        return SemanticPolicyResult(
            state=SemanticSignalState(
                sequence=sequence,
                usage=MappingProxyType(usage),
                turn_id=turn_id,
                scene_id=scene_id,
                chapter_id=chapter_id,
                recent_fingerprints=tuple(fingerprints),
                accepted_cause_groups=tuple(cause_groups),
            ),
            decisions=tuple(decisions),
        )

    def _rejection_reason(
        self,
        candidate: SemanticSignalCandidate,
        definition: SemanticSignalDefinition | None,
        *,
        state_sequence: int,
        usage: Mapping[str, int],
        fingerprints: list[tuple[str, int]],
        cause_groups: list[str],
        context: SemanticSignalContext,
        metric_ids: tuple[str, ...],
    ) -> str | None:
        if definition is None:
            return "unknown-signal"
        if not math.isfinite(candidate.confidence):
            return "invalid-confidence"
        if candidate.confidence < 0.0 or candidate.confidence > 1.0:
            return "invalid-confidence"
        if candidate.confidence < definition.minimum_confidence:
            return "low-confidence"
        if candidate.speech_act not in definition.allowed_speech_acts:
            return "speech-act-rejected"
        if not candidate.fingerprint:
            return "missing-fingerprint"
        if not candidate.cause_group:
            return "missing-cause-group"
        if not metric_ids:
            return "missing-metric-target"
        if (
            candidate.cause_group in context.suppressed_cause_groups
            or candidate.cause_group in cause_groups
        ):
            return "duplicate-cause-group"
        fingerprint_key = f"{candidate.signal_id}:{candidate.fingerprint}"
        for existing_key, accepted_sequence in reversed(fingerprints):
            if existing_key == fingerprint_key:
                if state_sequence - accepted_sequence < definition.repeat_window:
                    return "duplicate-fingerprint"
                break
        for metric_id in metric_ids:
            limits = (
                (f"turn:{metric_id}", definition.max_per_turn),
                (f"scene:{metric_id}", definition.max_per_scene),
                (f"chapter:{metric_id}", definition.max_per_chapter),
            )
            for key, limit in limits:
                if usage.get(key, 0) >= limit:
                    return "rate-limited"
        return None

    @staticmethod
    def _usage_keys(metric_ids: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            f"{scope}:{metric_id}"
            for metric_id in metric_ids
            for scope in ("turn", "scene", "chapter")
        )

    @staticmethod
    def _metric_ids(
        definition: SemanticSignalDefinition | None,
        strength: SignalStrength,
    ) -> tuple[str, ...]:
        if definition is None:
            return ()
        return tuple(
            sorted(
                {
                    str(effect.args[0])
                    for effect in definition.effects_by_strength.get(strength, ())
                    if effect.op in {"set", "increment", "add-set", "remove-set"}
                    and effect.args
                }
            )
        )

    @staticmethod
    def _usage_for_context(
        usage: Mapping[str, int],
        *,
        turn_id: str | None,
        scene_id: str | None,
        chapter_id: str | None,
        context: SemanticSignalContext,
    ) -> dict[str, int]:
        reset_scopes = {
            scope
            for scope, previous, current in (
                ("turn", turn_id, context.turn_id),
                ("scene", scene_id, context.scene_id),
                ("chapter", chapter_id, context.chapter_id),
            )
            if previous != current
        }
        return {
            key: value
            for key, value in usage.items()
            if key.partition(":")[0] not in reset_scopes
        }
