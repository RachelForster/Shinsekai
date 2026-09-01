"""Dynamic story-character resolution and rebuildable resource lifecycle."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from types import MappingProxyType
from typing import Any, Protocol

import yaml

from config.domain.feature_flags import FeatureFlag, FeatureFlagConfigManager
from core.story import (
    CastResolutionPlan,
    CharacterDefinition,
    CharacterRegistry,
    CharacterSource,
    CharacterSourceType,
    canonical_json,
)
from sdk.path_utils import safe_child_path, safe_existing_file_path


MAX_CHARACTER_PROFILE_BYTES = 2 * 1024 * 1024


class CharacterResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CharacterReadinessError(RuntimeError):
    def __init__(self, character_id: str, code: str, message: str) -> None:
        self.character_id = character_id
        self.code = code
        super().__init__(message)


class CastChangeRequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CharacterLoadPhase(str, Enum):
    NOT_LOADED = "not-loaded"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    id: str
    revision: str
    name: str
    color: str = ""
    setting: str = ""
    sprites: tuple[Mapping[str, Any], ...] = ()
    live2d: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    tts: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    memory_namespace: str = ""
    tool_permissions: tuple[str, ...] = ()
    source_root: str = ""


@dataclass(frozen=True, slots=True)
class CharacterResourceDiagnostic:
    character_id: str
    code: str
    message: str
    degraded: bool


@dataclass(slots=True)
class CharacterResourceRecord:
    phase: CharacterLoadPhase = CharacterLoadPhase.NOT_LOADED
    profile: CharacterProfile | None = None
    presentation: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    preloaded: bool = False
    last_used_at: float = 0.0


@dataclass(frozen=True, slots=True)
class ActorContext:
    profiles: Mapping[str, CharacterProfile]
    resources: Mapping[str, Mapping[str, Any]]
    speaker_allowlist: tuple[str, ...]
    memory_namespaces: Mapping[str, str]
    tool_permissions: Mapping[str, tuple[str, ...]]


class LocalCharacterLibrary(Protocol):
    def load_character(
        self,
        character_id: str,
        revision: str | None,
    ) -> Mapping[str, Any]: ...


class CharacterPresentationAdapter(Protocol):
    def load(self, profile: CharacterProfile) -> Mapping[str, Any]: ...

    def release(
        self,
        character_id: str,
        resources: Mapping[str, Any],
    ) -> None: ...


@dataclass(slots=True)
class _ImportToken:
    path: Path
    story_id: str
    expires_at: float
    content_digest: str


class CharacterImportTokenStore:
    """Authorize an explicit user-selected character file without exposing paths."""

    def __init__(self, flags: FeatureFlagConfigManager) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self._tokens: dict[str, _ImportToken] = {}

    def issue(
        self,
        path: str | Path,
        *,
        story_id: str,
        allowed_roots: Sequence[str | Path],
        ttl_seconds: float = 600.0,
    ) -> str:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        if ttl_seconds <= 0 or ttl_seconds > 3600:
            raise ValueError("import token lifetime must be between 0 and 3600 seconds")
        resolved = safe_existing_file_path(
            path,
            roots=allowed_roots,
            field="character import",
        )
        if resolved.stat().st_size > MAX_CHARACTER_PROFILE_BYTES:
            raise CharacterResolutionError(
                "character.import_too_large",
                "character import exceeds the size limit",
            )
        token = f"import_{secrets.token_urlsafe(32)}"
        self._tokens[token] = _ImportToken(
            path=resolved,
            story_id=story_id,
            expires_at=time.monotonic() + ttl_seconds,
            content_digest=_file_digest(resolved),
        )
        return token

    def resolve(self, token: str, *, story_id: str) -> tuple[Path, str]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        record = self._tokens.get(str(token))
        if record is None:
            raise CharacterResolutionError(
                "character.import_token",
                "character import token is invalid",
            )
        if time.monotonic() > record.expires_at:
            self._tokens.pop(str(token), None)
            raise CharacterResolutionError(
                "character.import_expired",
                "character import token has expired",
            )
        if record.story_id != story_id:
            raise CharacterResolutionError(
                "character.import_scope",
                "character import token belongs to another story",
            )
        if (
            not record.path.is_file()
            or _file_digest(record.path) != record.content_digest
        ):
            raise CharacterResolutionError(
                "character.import_changed",
                "selected character file changed after authorization",
            )
        return record.path, record.content_digest

    def revoke(self, token: str) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        self._tokens.pop(str(token), None)


class ConfigCharacterLibrary:
    """Read installed characters through the existing ConfigManager API."""

    def __init__(self, config_manager: Any) -> None:
        self.config_manager = config_manager

    def load_character(
        self,
        character_id: str,
        revision: str | None,
    ) -> Mapping[str, Any]:
        character = self.config_manager.get_character_by_name(character_id)
        if character is None:
            for candidate in self.config_manager.config.characters:
                if str(candidate.name).casefold() == character_id.casefold():
                    character = candidate
                    break
        if character is None:
            raise CharacterResolutionError(
                "character.local_missing",
                f"local character {character_id!r} is not installed",
            )
        payload = (
            character.model_dump(mode="json")
            if hasattr(character, "model_dump")
            else dict(character)
        )
        computed = _payload_digest(payload)
        if revision and revision != computed:
            raise CharacterResolutionError(
                "character.revision_mismatch",
                f"local character {character_id!r} does not match pinned revision",
            )
        return {**payload, "_content_digest": computed, "_revision": computed}


class CharacterSourceResolver:
    """Resolve all published source kinds into one immutable minimum profile."""

    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        *,
        story_id: str,
        story_root: str | Path,
        local_library: LocalCharacterLibrary,
        import_tokens: CharacterImportTokenStore | None = None,
        library_root: str | Path | None = None,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.story_id = story_id
        self.story_root = Path(story_root).resolve(strict=False)
        self.library_root = Path(library_root or self.story_root).resolve(strict=False)
        self.local_library = local_library
        self.import_tokens = import_tokens

    def resolve(self, definition: CharacterDefinition) -> CharacterProfile:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        source = definition.source
        source_root = self.story_root
        authorized_digest: str | None = None
        if source.type == CharacterSourceType.LOCAL_LIBRARY:
            source_root = self.library_root
            raw = self.local_library.load_character(
                str(source.character_id or definition.id),
                source.revision,
            )
            authorized_digest = str(raw.get("_content_digest") or "") or _payload_digest(
                raw
            )
        elif source.type == CharacterSourceType.USER_IMPORTED:
            if self.import_tokens is None or not source.path:
                raise CharacterResolutionError(
                    "character.import_token",
                    "user-imported characters require an import token",
                )
            path, authorized_digest = self.import_tokens.resolve(
                source.path,
                story_id=self.story_id,
            )
            source_root = path.parent
            raw = _read_profile(path)
        else:
            if not source.path:
                raise CharacterResolutionError(
                    "character.source_path",
                    "story-scoped character source path is missing",
                )
            path = safe_existing_file_path(
                safe_child_path(self.story_root, source.path),
                roots=(self.story_root,),
                field="story character",
            )
            authorized_digest = _file_digest(path)
            raw = _read_profile(path)

        revision = _payload_digest(raw)
        declared_revision = source.revision
        if source.content_digest:
            if authorized_digest is None:
                raise CharacterResolutionError(
                    "character.content_digest",
                    "character source cannot verify its content digest",
                )
            _require_digest(source.content_digest, authorized_digest, definition.id)
        if declared_revision:
            _require_digest(declared_revision, revision, definition.id)
        return _profile_from_mapping(
            definition.id,
            raw,
            revision=revision,
            source_root=source_root,
            story_root=self.story_root,
            story_scoped=source.type != CharacterSourceType.LOCAL_LIBRARY,
        )


class NoopCharacterPresentationAdapter:
    """Bind declared resources without opening heavyweight runtime handles."""

    def load(self, profile: CharacterProfile) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "sprites": profile.sprites,
                "live2d": profile.live2d,
                "tts": profile.tts,
            }
        )

    def release(
        self,
        character_id: str,
        resources: Mapping[str, Any],
    ) -> None:
        return None


class CharacterResourceManager:
    """Rebuildable profile and presentation cache, never authoritative state."""

    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        *,
        registry: CharacterRegistry,
        resolver: CharacterSourceResolver,
        presentation_adapter: CharacterPresentationAdapter | None = None,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.registry = registry
        self.resolver = resolver
        self.presentation_adapter = (
            presentation_adapter or NoopCharacterPresentationAdapter()
        )
        self.records: dict[str, CharacterResourceRecord] = {}
        self.active_character_ids: tuple[str, ...] = ()
        self.diagnostics: list[CharacterResourceDiagnostic] = []

    def register(self, definition: CharacterDefinition) -> CharacterProfile:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        if definition.id in self.registry.by_id:
            raise CharacterResolutionError(
                "character.duplicate",
                f"character {definition.id!r} is already registered",
            )
        previous = self.registry
        self.registry = replace(
            previous,
            characters=(*previous.characters, definition),
        )
        try:
            return self.load_profile(definition.id)
        except Exception:
            self.registry = previous
            self.records.pop(definition.id, None)
            raise

    def load_profile(self, character_id: str) -> CharacterProfile:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        definition = self.registry.by_id.get(character_id)
        if definition is None:
            raise CharacterReadinessError(
                character_id,
                "character.unregistered",
                f"character {character_id!r} is not registered",
            )
        record = self.records.setdefault(character_id, CharacterResourceRecord())
        if record.phase == CharacterLoadPhase.LOADED and record.profile is not None:
            record.last_used_at = time.monotonic()
            return record.profile
        record.phase = CharacterLoadPhase.LOADING
        record.error = ""
        try:
            profile = self.resolver.resolve(definition)
        except Exception as error:
            record.phase = CharacterLoadPhase.FAILED
            record.error = str(error)
            raise CharacterReadinessError(
                character_id,
                getattr(error, "code", "character.profile_failed"),
                str(error),
            ) from error
        record.phase = CharacterLoadPhase.LOADED
        record.profile = profile
        record.last_used_at = time.monotonic()
        return profile

    def preload(self, character_ids: Sequence[str]) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        for character_id in character_ids:
            profile = self.load_profile(character_id)
            record = self.records[character_id]
            record.preloaded = True
            self._load_presentation(profile, degraded=True)

    def require_presentation(self, character_id: str) -> Mapping[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        profile = self.load_profile(character_id)
        return self._load_presentation(profile, degraded=False)

    def activate(self, character_ids: Sequence[str]) -> ActorContext:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        next_active = tuple(dict.fromkeys(str(item) for item in character_ids))
        for character_id in next_active:
            try:
                profile = self.load_profile(character_id)
                self._load_presentation(profile, degraded=True)
            except CharacterReadinessError as error:
                self.diagnostics.append(
                    CharacterResourceDiagnostic(
                        character_id=character_id,
                        code=error.code,
                        message=str(error),
                        degraded=True,
                    )
                )
        for character_id in set(self.active_character_ids).difference(next_active):
            record = self.records.get(character_id)
            if record is not None and not record.preloaded:
                self.release(character_id)
        self.active_character_ids = next_active
        return self.actor_context()

    def release(self, character_id: str, *, force: bool = False) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        record = self.records.get(character_id)
        if record is None or (record.preloaded and not force):
            return
        if record.presentation:
            self.presentation_adapter.release(character_id, record.presentation)
        record.presentation = {}
        if force:
            record.profile = None
            record.phase = CharacterLoadPhase.NOT_LOADED
            record.preloaded = False

    def actor_context(self) -> ActorContext:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        profiles = {
            character_id: record.profile
            for character_id in self.active_character_ids
            if (record := self.records.get(character_id)) is not None
            and record.profile is not None
        }
        resources = {
            character_id: MappingProxyType(
                dict(self.records[character_id].presentation)
            )
            for character_id in profiles
        }
        return ActorContext(
            profiles=MappingProxyType(profiles),
            resources=MappingProxyType(resources),
            speaker_allowlist=(*profiles.keys(), "NARR", "SYSTEM"),
            memory_namespaces=MappingProxyType(
                {
                    character_id: profile.memory_namespace
                    for character_id, profile in profiles.items()
                }
            ),
            tool_permissions=MappingProxyType(
                {
                    character_id: profile.tool_permissions
                    for character_id, profile in profiles.items()
                }
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        return {
            "activeCharacterIds": list(self.active_character_ids),
            "characters": {
                character_id: {
                    "phase": record.phase.value,
                    "presentationLoaded": bool(record.presentation),
                    "preloaded": record.preloaded,
                    "error": record.error,
                }
                for character_id, record in sorted(self.records.items())
            },
            "diagnostics": [
                {
                    "characterId": item.character_id,
                    "code": item.code,
                    "message": item.message,
                    "degraded": item.degraded,
                }
                for item in self.diagnostics[-64:]
            ],
        }

    def _load_presentation(
        self,
        profile: CharacterProfile,
        *,
        degraded: bool,
    ) -> Mapping[str, Any]:
        record = self.records[profile.id]
        if record.presentation:
            return record.presentation
        try:
            record.presentation = dict(self.presentation_adapter.load(profile))
        except Exception as error:
            diagnostic = CharacterResourceDiagnostic(
                character_id=profile.id,
                code="character.presentation_failed",
                message=str(error),
                degraded=degraded,
            )
            self.diagnostics.append(diagnostic)
            if not degraded:
                raise CharacterReadinessError(
                    profile.id,
                    diagnostic.code,
                    diagnostic.message,
                ) from error
        return MappingProxyType(dict(record.presentation))


class StoryCastApplicationService:
    """Apply readiness fallback before commit and resource binding after commit."""

    def __init__(
        self,
        flags: FeatureFlagConfigManager,
        resources: CharacterResourceManager,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.flags = flags
        self.resources = resources

    def prepare(self, plan: CastResolutionPlan) -> CastResolutionPlan:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        required = set(plan.required_character_ids)
        active: list[str] = []
        excluded = dict(plan.excluded)
        for character_id in plan.active_character_ids:
            try:
                self.resources.load_profile(character_id)
                if plan.requires_loaded_assets:
                    self.resources.require_presentation(character_id)
            except CharacterReadinessError:
                if (
                    character_id not in required
                    and plan.on_load_failure == "continue-without-optional"
                ):
                    excluded[character_id] = "profile-load-failed"
                    continue
                raise
            active.append(character_id)
        if len(active) < plan.minimum_active:
            raise CharacterReadinessError(
                "",
                "cast.min_active_after_fallback",
                "resource fallback would violate minActive",
            )
        bindings = {
            role: character_id
            for role, character_id in plan.role_bindings.items()
            if character_id in active
        }
        return replace(
            plan,
            active_character_ids=tuple(active),
            role_bindings=MappingProxyType(bindings),
            excluded=MappingProxyType(excluded),
        )

    def committed(self, plan: CastResolutionPlan) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        self.resources.activate(plan.active_character_ids)

    def rebuild(self, active_character_ids: Sequence[str]) -> ActorContext:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        for character_id in active_character_ids:
            self.resources.load_profile(character_id)
        return self.resources.activate(active_character_ids)

    def preload(self, character_ids: Sequence[str]) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        self.resources.preload(character_ids)

    def register(self, definition: CharacterDefinition) -> CharacterProfile:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        return self.resources.register(definition)

    def request_entry(
        self,
        active_character_ids: Sequence[str],
        character_id: str,
        *,
        current_node_id: str,
        current_revision: int,
        expected_node_id: str,
        expected_revision: int,
        maximum_active: int,
    ) -> CastResolutionPlan:
        self._validate_request_boundary(
            current_node_id,
            current_revision,
            expected_node_id,
            expected_revision,
        )
        active = tuple(dict.fromkeys(str(item) for item in active_character_ids))
        if character_id in active:
            return self._change_plan(active, maximum_active=maximum_active)
        return self.prepare(
            self._change_plan(
                (*active, character_id),
                maximum_active=maximum_active,
            )
        )

    def request_exit(
        self,
        active_character_ids: Sequence[str],
        character_id: str,
        *,
        current_node_id: str,
        current_revision: int,
        expected_node_id: str,
        expected_revision: int,
        minimum_active: int = 0,
        maximum_active: int = 8,
    ) -> CastResolutionPlan:
        self._validate_request_boundary(
            current_node_id,
            current_revision,
            expected_node_id,
            expected_revision,
        )
        active = tuple(
            item for item in dict.fromkeys(active_character_ids) if item != character_id
        )
        if len(active) < minimum_active:
            raise CastChangeRequestError(
                "cast.min_active",
                "character exit would violate minActive",
            )
        return self._change_plan(
            active,
            minimum_active=minimum_active,
            maximum_active=maximum_active,
        )

    def request_replace(
        self,
        active_character_ids: Sequence[str],
        outgoing_character_id: str,
        incoming_character_id: str,
        *,
        current_node_id: str,
        current_revision: int,
        expected_node_id: str,
        expected_revision: int,
        maximum_active: int,
    ) -> CastResolutionPlan:
        self._validate_request_boundary(
            current_node_id,
            current_revision,
            expected_node_id,
            expected_revision,
        )
        active = list(dict.fromkeys(str(item) for item in active_character_ids))
        if outgoing_character_id not in active:
            raise CastChangeRequestError(
                "cast.character_not_active",
                f"character {outgoing_character_id!r} is not active",
            )
        index = active.index(outgoing_character_id)
        active[index] = incoming_character_id
        return self.prepare(
            self._change_plan(
                tuple(dict.fromkeys(active)),
                maximum_active=maximum_active,
            )
        )

    def unload(self, character_id: str) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        self.resources.release(character_id, force=True)

    def snapshot(self) -> dict[str, Any]:
        return self.resources.snapshot()

    def chat_patch(self) -> dict[str, Any]:
        self.flags.require(FeatureFlag.STORY_SYSTEM)
        context = self.resources.actor_context()
        sprites = []
        for character_id, profile in context.profiles.items():
            if not profile.sprites:
                continue
            sprite = profile.sprites[0]
            path = str(sprite.get("path") or "")
            if not path:
                continue
            sprites.append(
                {
                    "id": f"story:{character_id}",
                    "characterName": character_id,
                    "label": profile.name,
                    "path": path,
                    "scale": sprite.get("scale", 1.0),
                }
            )
        return {
            "storyResources": self.resources.snapshot(),
            "actorContext": {
                "speakerAllowlist": list(context.speaker_allowlist),
                "activeCharacterIds": list(context.profiles),
            },
            **({"sprites": sprites} if sprites else {}),
        }

    @staticmethod
    def _validate_request_boundary(
        current_node_id: str,
        current_revision: int,
        expected_node_id: str,
        expected_revision: int,
    ) -> None:
        if current_node_id != expected_node_id:
            raise CastChangeRequestError(
                "cast.node_conflict",
                "character request targets a stale story node",
            )
        if current_revision != expected_revision:
            raise CastChangeRequestError(
                "cast.revision_conflict",
                "character request targets a stale story revision",
            )

    def _change_plan(
        self,
        active_character_ids: Sequence[str],
        *,
        minimum_active: int = 0,
        maximum_active: int,
    ) -> CastResolutionPlan:
        active = tuple(str(item) for item in active_character_ids)
        if len(active) > maximum_active:
            raise CastChangeRequestError(
                "cast.max_active",
                "character request would violate maxActive",
            )
        unknown = set(active).difference(self.resources.registry.by_id)
        if unknown:
            raise CastChangeRequestError(
                "cast.unregistered",
                f"character request contains unregistered IDs: {', '.join(sorted(unknown))}",
            )
        return CastResolutionPlan(
            active_character_ids=active,
            role_bindings=MappingProxyType({}),
            excluded=MappingProxyType({}),
            required_character_ids=active,
            on_load_failure="error",
            minimum_active=minimum_active,
            maximum_active=maximum_active,
        )


def migrate_selected_characters(
    flags: FeatureFlagConfigManager,
    selected_characters: Sequence[str],
    *,
    local_library: LocalCharacterLibrary,
) -> CharacterRegistry:
    """Explicitly convert legacy selections into a pinned story registry."""
    flags.require(FeatureFlag.STORY_SYSTEM)
    definitions = []
    seen = set()
    for raw_id in selected_characters:
        character_id = str(raw_id).strip()
        if not character_id or character_id in seen:
            continue
        seen.add(character_id)
        payload = local_library.load_character(character_id, None)
        revision = str(payload.get("_revision") or _payload_digest(payload))
        definitions.append(
            CharacterDefinition(
                id=character_id,
                source=CharacterSource(
                    type=CharacterSourceType.LOCAL_LIBRARY,
                    character_id=character_id,
                    revision=revision,
                ),
            )
        )
    return CharacterRegistry(
        characters=tuple(definitions),
        initial_cast=tuple(item.id for item in definitions),
    )


def materialize_imported_character(
    flags: FeatureFlagConfigManager,
    import_tokens: CharacterImportTokenStore,
    *,
    token: str,
    story_id: str,
    story_root: str | Path,
    destination: str,
) -> tuple[Path, str]:
    """Copy an authorized import into story-owned storage atomically."""
    flags.require(FeatureFlag.STORY_SYSTEM)
    source, _digest = import_tokens.resolve(token, story_id=story_id)
    root = Path(story_root).resolve(strict=False)
    target = safe_child_path(root, destination)
    if target.suffix.lower() not in {".yaml", ".yml", ".json", ".char"}:
        raise CharacterResolutionError(
            "character.import_extension",
            "import destination has an unsupported extension",
        )
    payload = _read_profile(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            _write_profile_payload(
                file,
                payload,
                suffix=target.suffix.lower(),
            )
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    import_tokens.revoke(token)
    return target, _file_digest(target)


def _read_profile(path: Path) -> Mapping[str, Any]:
    try:
        if path.stat().st_size > MAX_CHARACTER_PROFILE_BYTES:
            raise CharacterResolutionError(
                "character.profile_too_large",
                "character profile exceeds the size limit",
            )
        text = path.read_text(encoding="utf-8")
        value = (
            json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
        )
    except CharacterResolutionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise CharacterResolutionError(
            "character.profile_read",
            f"character profile is unreadable: {error}",
        ) from error
    if not isinstance(value, Mapping):
        raise CharacterResolutionError(
            "character.profile_schema",
            "character profile must be an object",
        )
    return value


def _profile_from_mapping(
    character_id: str,
    raw: Mapping[str, Any],
    *,
    revision: str,
    source_root: Path,
    story_root: Path,
    story_scoped: bool,
) -> CharacterProfile:
    name = str(raw.get("name") or raw.get("id") or character_id).strip()
    if not name:
        raise CharacterResolutionError(
            "character.profile_name",
            "character profile name is empty",
        )
    raw_sprites = raw.get("sprites", ())
    if not isinstance(raw_sprites, Sequence) or isinstance(
        raw_sprites, (str, bytes, bytearray)
    ):
        raise CharacterResolutionError(
            "character.profile_sprites",
            "character sprites must be a list",
        )
    sprites = []
    for item in raw_sprites:
        if not isinstance(item, Mapping):
            raise CharacterResolutionError(
                "character.profile_sprites",
                "character sprite must be an object",
            )
        sprites.append(
            MappingProxyType(
                _validated_resource_mapping(
                    item,
                    source_root=source_root,
                    story_root=story_root,
                    story_scoped=story_scoped,
                )
            )
        )
    live2d_raw = raw.get("live2d", {})
    tts_raw = raw.get("tts", {})
    if not isinstance(live2d_raw, Mapping) or not isinstance(tts_raw, Mapping):
        raise CharacterResolutionError(
            "character.profile_resources",
            "live2d and tts profiles must be objects",
        )
    permissions = raw.get("toolPermissions", raw.get("tool_permissions", ()))
    if not isinstance(permissions, Sequence) or isinstance(
        permissions, (str, bytes, bytearray)
    ):
        raise CharacterResolutionError(
            "character.profile_permissions",
            "tool permissions must be a list",
        )
    return CharacterProfile(
        id=character_id,
        revision=revision,
        name=name,
        color=str(raw.get("color") or ""),
        setting=str(raw.get("characterSetting") or raw.get("character_setting") or ""),
        sprites=tuple(sprites),
        live2d=MappingProxyType(dict(live2d_raw)),
        tts=MappingProxyType(dict(tts_raw)),
        memory_namespace=str(
            raw.get("memoryNamespace")
            or raw.get("memory_namespace")
            or f"story:{character_id}"
        ),
        tool_permissions=tuple(str(item) for item in permissions),
        source_root=str(source_root),
    )


def _validated_resource_mapping(
    raw: Mapping[str, Any],
    *,
    source_root: Path,
    story_root: Path,
    story_scoped: bool,
) -> dict[str, Any]:
    result = dict(raw)
    for key in ("path", "voice_path", "voicePath"):
        value = result.get(key)
        if not value:
            continue
        candidate = Path(str(value))
        if story_scoped:
            if candidate.is_absolute():
                raise CharacterResolutionError(
                    "character.resource_path",
                    "story-scoped character resources must use relative paths",
                )
            resolved = safe_child_path(story_root, candidate)
        else:
            resolved = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else safe_child_path(source_root, candidate)
            )
        result[key] = str(resolved)
    return result


def _write_profile_payload(file: Any, payload: Mapping[str, Any], *, suffix: str) -> None:
    data = dict(payload)
    if suffix == ".json":
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        return
    yaml.safe_dump(data, file, allow_unicode=True, sort_keys=True)


def _payload_digest(payload: Mapping[str, Any]) -> str:
    filtered = {
        str(key): value
        for key, value in payload.items()
        if key not in {"_content_digest", "_revision"}
    }
    return (
        f"sha256:{hashlib.sha256(canonical_json(filtered).encode('utf-8')).hexdigest()}"
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _require_digest(expected: str, actual: str, character_id: str) -> None:
    if expected != actual:
        raise CharacterResolutionError(
            "character.revision_mismatch",
            f"character {character_id!r} does not match its pinned revision",
        )
