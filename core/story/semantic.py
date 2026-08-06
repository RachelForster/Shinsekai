"""Pure semantic-signal acceptance, deduplication, and quota policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
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
        fingerprints = list(state.recent_fingerprints)
        cause_groups = list(state.accepted_cause_groups)
        decisions: list[SemanticSignalDecision] = []

        for candidate in candidates:
            definition = definitions.get(candidate.signal_id)
            reason = self._rejection_reason(
                candidate,
                definition,
                state_sequence=sequence,
                usage=usage,
                fingerprints=fingerprints,
                cause_groups=cause_groups,
                context=context,
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
            fingerprint_key = f"{candidate.signal_id}:{candidate.fingerprint}"
            fingerprints.append((fingerprint_key, sequence))
            cause_groups.append(candidate.cause_group)
            for key in self._usage_keys(candidate.signal_id, context):
                usage[key] = usage.get(key, 0) + 1
            effects = tuple(definition.effects_by_strength.get(candidate.strength, ()))
            decisions.append(
                SemanticSignalDecision(
                    candidate=candidate,
                    accepted=True,
                    reason_code="accepted",
                    effects=effects,
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
    ) -> str | None:
        if definition is None:
            return "unknown-signal"
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
        limits = (
            (f"turn:{context.turn_id}:{candidate.signal_id}", definition.max_per_turn),
            (
                f"scene:{context.scene_id}:{candidate.signal_id}",
                definition.max_per_scene,
            ),
            (
                f"chapter:{context.chapter_id}:{candidate.signal_id}",
                definition.max_per_chapter,
            ),
        )
        for key, limit in limits:
            if usage.get(key, 0) >= limit:
                return "rate-limited"
        return None

    @staticmethod
    def _usage_keys(
        signal_id: str,
        context: SemanticSignalContext,
    ) -> tuple[str, str, str]:
        return (
            f"turn:{context.turn_id}:{signal_id}",
            f"scene:{context.scene_id}:{signal_id}",
            f"chapter:{context.chapter_id}:{signal_id}",
        )
