from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from application.story import (
    CastChangeRequestError,
    CharacterImportTokenStore,
    CharacterLoadPhase,
    CharacterReadinessError,
    CharacterResolutionError,
    CharacterResourceManager,
    CharacterSourceResolver,
    ConfigCharacterLibrary,
    StoryCastApplicationService,
    StorySession,
    materialize_imported_character,
    migrate_selected_characters,
)
from config.domain.feature_flags import (
    FeatureDisabledError,
    FeatureFlag,
    FeatureFlagConfigManager,
)
from core.story import (
    CastResolutionPlan,
    CharacterDefinition,
    CharacterRegistry,
    CharacterSource,
    CharacterSourceType,
    SelectChoice,
    StoryCompiler,
    StoryRuntime,
    canonical_json,
    parse_story_project,
)
from test.unit.core.story.story_fixtures import campus_mystery_source


def _flags(enabled: bool = True) -> FeatureFlagConfigManager:
    return FeatureFlagConfigManager(
        environ={},
        overrides={FeatureFlag.STORY_SYSTEM: enabled},
    )


class _Library:
    def __init__(self, profiles: dict[str, dict] | None = None) -> None:
        self.profiles = profiles or {}
        self.calls: list[str] = []

    def load_character(self, character_id: str, revision: str | None):
        self.calls.append(character_id)
        if character_id not in self.profiles:
            raise CharacterResolutionError("missing", f"missing {character_id}")
        return dict(self.profiles[character_id])


class _Presentation:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.loaded: list[str] = []
        self.released: list[str] = []

    def load(self, profile):
        self.loaded.append(profile.id)
        if profile.id in self.fail:
            raise RuntimeError(f"presentation failed for {profile.id}")
        return {"bound": profile.id}

    def release(self, character_id, _resources):
        self.released.append(character_id)


def _definition(
    character_id: str,
    source_type: CharacterSourceType,
    *,
    path: str | None = None,
    revision: str | None = None,
    content_digest: str | None = None,
) -> CharacterDefinition:
    return CharacterDefinition(
        id=character_id,
        source=CharacterSource(
            type=source_type,
            character_id=(
                character_id
                if source_type == CharacterSourceType.LOCAL_LIBRARY
                else None
            ),
            path=path,
            revision=revision,
            content_digest=content_digest,
        ),
    )


def _write_profile(path: Path, name: str, *, sprite: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "characterSetting": f"Setting for {name}",
        "sprites": ([{"path": sprite}] if sprite else []),
        "toolPermissions": ["memory.search"],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_all_published_character_source_interfaces_resolve(tmp_path) -> None:
    flags = _flags()
    root = tmp_path / "story"
    embedded = root / "characters" / "embedded.yaml"
    generated = root / "characters" / "generated.yaml"
    _write_profile(embedded, "Embedded")
    _write_profile(generated, "Generated")
    import_root = tmp_path / "imports"
    imported = import_root / "user.char"
    _write_profile(imported, "Imported")
    tokens = CharacterImportTokenStore(flags)
    token = tokens.issue(
        imported,
        story_id="story-1",
        allowed_roots=(import_root,),
    )
    library = _Library({"local": {"name": "Local", "sprites": []}})
    resolver = CharacterSourceResolver(
        flags,
        story_id="story-1",
        story_root=root,
        local_library=library,
        import_tokens=tokens,
    )

    profiles = [
        resolver.resolve(_definition("local", CharacterSourceType.LOCAL_LIBRARY)),
        resolver.resolve(
            _definition(
                "embedded",
                CharacterSourceType.EMBEDDED,
                path="characters/embedded.yaml",
            )
        ),
        resolver.resolve(
            _definition(
                "imported",
                CharacterSourceType.USER_IMPORTED,
                path=token,
            )
        ),
        resolver.resolve(
            _definition(
                "generated",
                CharacterSourceType.AUTHOR_GENERATED,
                path="characters/generated.yaml",
            )
        ),
    ]

    assert [profile.name for profile in profiles] == [
        "Local",
        "Embedded",
        "Imported",
        "Generated",
    ]
    assert profiles[1].tool_permissions == ("memory.search",)


def test_story_scoped_path_escape_and_content_change_are_rejected(tmp_path) -> None:
    flags = _flags()
    root = tmp_path / "story"
    root.mkdir()
    outside = tmp_path / "outside.yaml"
    _write_profile(outside, "Outside")
    resolver = CharacterSourceResolver(
        flags,
        story_id="story-1",
        story_root=root,
        local_library=_Library(),
    )

    with pytest.raises((PermissionError, CharacterResolutionError)):
        resolver.resolve(
            _definition(
                "outside",
                CharacterSourceType.EMBEDDED,
                path="../outside.yaml",
            )
        )

    inside = root / "inside.yaml"
    _write_profile(inside, "Inside")
    wrong_digest = f"sha256:{'0' * 64}"
    with pytest.raises(CharacterResolutionError) as exc_info:
        resolver.resolve(
            _definition(
                "inside",
                CharacterSourceType.EMBEDDED,
                path="inside.yaml",
                content_digest=wrong_digest,
            )
        )
    assert exc_info.value.code == "character.revision_mismatch"


def test_import_token_is_story_scoped_and_materialized_atomically(tmp_path) -> None:
    flags = _flags()
    import_root = tmp_path / "imports"
    source = import_root / "selected.char"
    _write_profile(source, "Selected")
    tokens = CharacterImportTokenStore(flags)
    token = tokens.issue(
        source,
        story_id="story-a",
        allowed_roots=(import_root,),
    )

    with pytest.raises(CharacterResolutionError) as exc_info:
        tokens.resolve(token, story_id="story-b")
    assert exc_info.value.code == "character.import_scope"

    target, digest = materialize_imported_character(
        flags,
        tokens,
        token=token,
        story_id="story-a",
        story_root=tmp_path / "story",
        destination="characters/selected.yaml",
    )

    assert target.is_file()
    assert digest == f"sha256:{hashlib.sha256(target.read_bytes()).hexdigest()}"
    with pytest.raises(CharacterResolutionError):
        tokens.resolve(token, story_id="story-a")


def test_optional_profile_failure_uses_declared_precommit_fallback(tmp_path) -> None:
    flags = _flags()
    registry = CharacterRegistry(
        characters=(
            _definition("required", CharacterSourceType.LOCAL_LIBRARY),
            _definition("optional", CharacterSourceType.LOCAL_LIBRARY),
        )
    )
    resources = CharacterResourceManager(
        flags,
        registry=registry,
        resolver=CharacterSourceResolver(
            flags,
            story_id="story-1",
            story_root=tmp_path,
            local_library=_Library({"required": {"name": "Required", "sprites": []}}),
        ),
    )
    service = StoryCastApplicationService(flags, resources)
    plan = CastResolutionPlan(
        active_character_ids=("required", "optional"),
        role_bindings={},
        excluded={},
        required_character_ids=("required",),
        on_load_failure="continue-without-optional",
        minimum_active=1,
    )

    prepared = service.prepare(plan)

    assert prepared.active_character_ids == ("required",)
    assert prepared.excluded["optional"] == "profile-load-failed"
    assert resources.records["optional"].phase == CharacterLoadPhase.FAILED


def test_required_profile_failure_rejects_before_story_commit(tmp_path) -> None:
    flags = _flags()
    source = _disjoint_cast_source()
    root = tmp_path / "story"
    program = StoryCompiler().compile(parse_story_project(source))
    service = StoryCastApplicationService(
        flags,
        CharacterResourceManager(
            flags,
            registry=program.character_registry,
            resolver=CharacterSourceResolver(
                flags,
                story_id=program.story_id,
                story_root=root,
                local_library=_Library(),
            ),
        ),
    )

    with pytest.raises(CharacterReadinessError):
        StorySession.create(
            StoryRuntime(program),
            flags,
            command_id="start-1",
            cast_plan_preparer=service.prepare,
            cast_plan_committed=service.committed,
        )


def test_disjoint_adjacent_cast_loads_and_releases_after_commit(tmp_path) -> None:
    flags = _flags()
    root = tmp_path / "story"
    _write_profile(root / "characters" / "alice.yaml", "Alice")
    _write_profile(root / "characters" / "bob.yaml", "Bob")
    program = StoryCompiler().compile(parse_story_project(_disjoint_cast_source()))
    presentation = _Presentation()
    resources = CharacterResourceManager(
        flags,
        registry=program.character_registry,
        resolver=CharacterSourceResolver(
            flags,
            story_id=program.story_id,
            story_root=root,
            local_library=_Library(),
        ),
        presentation_adapter=presentation,
    )
    service = StoryCastApplicationService(flags, resources)
    session = StorySession.create(
        StoryRuntime(program),
        flags,
        command_id="start-1",
        cast_plan_preparer=service.prepare,
        cast_plan_committed=service.committed,
    )
    started_revision = session.active_branch.state.revision

    session.execute(
        SelectChoice(
            command_id="choice-1",
            expected_revision=started_revision,
            choice_id="prepare-investigation",
            expected_node_id="transfer-day",
        )
    )

    assert session.active_branch.state.cast_state.active_character_ids == ("bob",)
    assert presentation.loaded == ["alice", "bob"]
    assert presentation.released == ["alice"]
    assert resources.actor_context().speaker_allowlist == ("bob", "NARR", "SYSTEM")


def test_postcommit_presentation_failure_is_degraded_without_state_rollback(
    tmp_path,
) -> None:
    flags = _flags()
    root = tmp_path / "story"
    _write_profile(root / "characters" / "alice.yaml", "Alice")
    _write_profile(root / "characters" / "bob.yaml", "Bob")
    program = StoryCompiler().compile(parse_story_project(_disjoint_cast_source()))
    presentation = _Presentation(fail={"bob"})
    resources = CharacterResourceManager(
        flags,
        registry=program.character_registry,
        resolver=CharacterSourceResolver(
            flags,
            story_id=program.story_id,
            story_root=root,
            local_library=_Library(),
        ),
        presentation_adapter=presentation,
    )
    service = StoryCastApplicationService(flags, resources)
    session = StorySession.create(
        StoryRuntime(program),
        flags,
        command_id="start-1",
        cast_plan_preparer=service.prepare,
        cast_plan_committed=service.committed,
    )
    session.execute(
        SelectChoice(
            command_id="choice-1",
            expected_revision=1,
            choice_id="prepare-investigation",
            expected_node_id="transfer-day",
        )
    )

    assert session.active_branch.state.current_node_id == "old-school-gate"
    assert session.active_branch.state.revision == 2
    assert resources.diagnostics[-1].code == "character.presentation_failed"
    assert resources.diagnostics[-1].degraded is True


def test_character_change_requests_enforce_revision_registration_and_limits(
    tmp_path,
) -> None:
    flags = _flags()
    registry = CharacterRegistry(
        characters=(
            _definition("alice", CharacterSourceType.LOCAL_LIBRARY),
            _definition("bob", CharacterSourceType.LOCAL_LIBRARY),
        )
    )
    service = StoryCastApplicationService(
        flags,
        CharacterResourceManager(
            flags,
            registry=registry,
            resolver=CharacterSourceResolver(
                flags,
                story_id="story-1",
                story_root=tmp_path,
                local_library=_Library(
                    {
                        "alice": {"name": "Alice", "sprites": []},
                        "bob": {"name": "Bob", "sprites": []},
                    }
                ),
            ),
        ),
    )

    entered = service.request_entry(
        ("alice",),
        "bob",
        current_node_id="gate",
        current_revision=4,
        expected_node_id="gate",
        expected_revision=4,
        maximum_active=2,
    )
    replaced = service.request_replace(
        ("alice",),
        "alice",
        "bob",
        current_node_id="gate",
        current_revision=4,
        expected_node_id="gate",
        expected_revision=4,
        maximum_active=2,
    )

    assert entered.active_character_ids == ("alice", "bob")
    assert replaced.active_character_ids == ("bob",)
    with pytest.raises(CastChangeRequestError) as exc_info:
        service.request_exit(
            ("alice",),
            "alice",
            current_node_id="gate",
            current_revision=4,
            expected_node_id="gate",
            expected_revision=3,
            minimum_active=1,
        )
    assert exc_info.value.code == "cast.revision_conflict"


def test_resource_cache_rebuilds_from_persisted_active_cast(tmp_path) -> None:
    flags = _flags()
    root = tmp_path / "story"
    _write_profile(root / "characters" / "alice.yaml", "Alice")
    registry = CharacterRegistry(
        characters=(
            _definition(
                "alice",
                CharacterSourceType.EMBEDDED,
                path="characters/alice.yaml",
            ),
        )
    )
    presentation = _Presentation()
    service = StoryCastApplicationService(
        flags,
        CharacterResourceManager(
            flags,
            registry=registry,
            resolver=CharacterSourceResolver(
                flags,
                story_id="story-1",
                story_root=root,
                local_library=_Library(),
            ),
            presentation_adapter=presentation,
        ),
    )

    context = service.rebuild(("alice",))

    assert context.speaker_allowlist == ("alice", "NARR", "SYSTEM")
    assert presentation.loaded == ["alice"]


def test_legacy_selected_characters_migrate_only_when_flag_is_enabled() -> None:
    library = _Library(
        {
            "Alice": {"name": "Alice", "sprites": []},
            "Bob": {"name": "Bob", "sprites": []},
        }
    )
    registry = migrate_selected_characters(
        _flags(),
        ["Alice", "Bob", "Alice"],
        local_library=library,
    )

    assert registry.initial_cast == ("Alice", "Bob")
    assert all(item.source.revision for item in registry.characters)
    with pytest.raises(FeatureDisabledError):
        migrate_selected_characters(
            _flags(False),
            ["Alice"],
            local_library=library,
        )


def _disjoint_cast_source() -> dict:
    source = deepcopy(campus_mystery_source())
    source["cast"] = {
        "initialCast": ["alice"],
        "characters": [
            {
                "id": "alice",
                "source": {
                    "type": "embedded",
                    "path": "characters/alice.yaml",
                },
            },
            {
                "id": "bob",
                "source": {
                    "type": "embedded",
                    "path": "characters/bob.yaml",
                },
            },
        ],
    }
    nodes = source["narrativeGraph"]["nodes"]
    nodes[0]["castPolicy"] = {
        "mode": "fixed",
        "required": ["alice"],
        "constraints": {"minActive": 1, "maxActive": 1},
    }
    nodes[1]["castPolicy"] = {
        "mode": "fixed",
        "required": ["bob"],
        "constraints": {"minActive": 1, "maxActive": 1},
    }
    nodes[2]["castPolicy"] = {
        "mode": "fixed",
        "required": ["bob"],
        "constraints": {"minActive": 1, "maxActive": 1},
    }
    return source


def _payload_digest(payload: dict) -> str:
    filtered = {
        key: value
        for key, value in payload.items()
        if key not in {"_content_digest", "_revision"}
    }
    return f"sha256:{hashlib.sha256(canonical_json(filtered).encode('utf-8')).hexdigest()}"


class _InstalledCharacter:
    def __init__(self, payload: dict) -> None:
        self.name = str(payload["name"])
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return dict(self._payload)


def test_materialize_imported_character_writes_json_for_json_destination(tmp_path) -> None:
    flags = _flags()
    import_root = tmp_path / "imports"
    source = import_root / "selected.char"
    _write_profile(source, "Selected")
    tokens = CharacterImportTokenStore(flags)
    token = tokens.issue(source, story_id="story-a", allowed_roots=(import_root,))
    story_root = tmp_path / "story"

    target, _digest = materialize_imported_character(
        flags,
        tokens,
        token=token,
        story_id="story-a",
        story_root=story_root,
        destination="characters/selected.json",
    )

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["name"] == "Selected"
    profile = CharacterSourceResolver(
        flags,
        story_id="story-a",
        story_root=story_root,
        local_library=_Library(),
    ).resolve(
        _definition(
            "selected",
            CharacterSourceType.EMBEDDED,
            path="characters/selected.json",
        )
    )
    assert profile.name == "Selected"


def test_local_library_pins_observe_installed_digest_and_content_digest(tmp_path) -> None:
    flags = _flags()
    payload = {"name": "Ling", "sprites": [], "characterSetting": "student"}
    digest = _payload_digest(payload)
    library = ConfigCharacterLibrary(
        SimpleNamespace(
            config=SimpleNamespace(characters=[_InstalledCharacter(payload)]),
            get_character_by_name=lambda name: (
                _InstalledCharacter(payload) if name == "Ling" else None
            ),
        )
    )
    observed = library.load_character("Ling", None)
    assert observed["_revision"] == digest
    assert observed["_content_digest"] == digest

    with pytest.raises(CharacterResolutionError) as stale_pin:
        library.load_character("Ling", "v1")
    assert stale_pin.value.code == "character.revision_mismatch"

    changed = library.load_character("Ling", digest)
    assert changed["_revision"] == digest

    resolver = CharacterSourceResolver(
        flags,
        story_id="story-1",
        story_root=tmp_path / "stories" / "case",
        local_library=library,
        library_root=tmp_path,
    )
    profile = resolver.resolve(
        _definition(
            "Ling",
            CharacterSourceType.LOCAL_LIBRARY,
            content_digest=digest,
        )
    )
    assert profile.revision == digest

    with pytest.raises(CharacterResolutionError) as digest_info:
        resolver.resolve(
            _definition(
                "Ling",
                CharacterSourceType.LOCAL_LIBRARY,
                content_digest=f"sha256:{'0' * 64}",
            )
        )
    assert digest_info.value.code == "character.revision_mismatch"

    payload["characterSetting"] = "changed"
    with pytest.raises(CharacterResolutionError) as changed_info:
        library.load_character("Ling", digest)
    assert changed_info.value.code == "character.revision_mismatch"


def test_local_library_sprites_resolve_against_library_root(tmp_path) -> None:
    flags = _flags()
    project = tmp_path / "project"
    story = project / "stories" / "case"
    sprite = project / "data" / "sprite" / "ling.png"
    sprite.parent.mkdir(parents=True)
    sprite.write_bytes(b"png")
    story.mkdir(parents=True)
    resolver = CharacterSourceResolver(
        flags,
        story_id="story-1",
        story_root=story,
        local_library=_Library(
            {"ling": {"name": "Ling", "sprites": [{"path": "data/sprite/ling.png"}]}}
        ),
        library_root=project,
    )

    profile = resolver.resolve(_definition("ling", CharacterSourceType.LOCAL_LIBRARY))

    assert Path(profile.sprites[0]["path"]) == sprite.resolve()
    assert not str(profile.sprites[0]["path"]).replace("\\", "/").endswith(
        "stories/case/data/sprite/ling.png"
    )


def test_branch_switch_rebuilds_cast_resources(tmp_path) -> None:
    flags = _flags()
    root = tmp_path / "story"
    _write_profile(root / "characters" / "alice.yaml", "Alice")
    _write_profile(root / "characters" / "bob.yaml", "Bob")
    program = StoryCompiler().compile(parse_story_project(_disjoint_cast_source()))
    presentation = _Presentation()
    resources = CharacterResourceManager(
        flags,
        registry=program.character_registry,
        resolver=CharacterSourceResolver(
            flags,
            story_id=program.story_id,
            story_root=root,
            local_library=_Library(),
        ),
        presentation_adapter=presentation,
    )
    service = StoryCastApplicationService(flags, resources)
    session = StorySession.create(
        StoryRuntime(program),
        flags,
        command_id="start-1",
        cast_plan_preparer=service.prepare,
        cast_plan_committed=service.committed,
        cast_resources_rebuilder=service.rebuild,
    )
    started_revision = session.active_branch.state.revision
    session.execute(
        SelectChoice(
            command_id="choice-1",
            expected_revision=started_revision,
            choice_id="prepare-investigation",
            expected_node_id="transfer-day",
        )
    )
    assert resources.active_character_ids == ("bob",)

    session.fork("branch-2", generation=1)

    assert session.active_branch_id == "branch-2"
    assert session.active_branch.state.cast_state.active_character_ids == ("alice",)
    assert resources.active_character_ids == ("alice",)

    session.switch_branch("main")

    assert resources.active_character_ids == ("bob",)
