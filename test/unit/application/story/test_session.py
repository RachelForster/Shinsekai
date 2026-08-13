from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json

import pytest

from application.story import (
    JsonGlobalStoryProgressStore,
    JsonStorySessionRepository,
    StoryProgramMismatchError,
    StorySession,
)
from application.story.persistence import global_progress_filename
from config.feature_flags import (
    FeatureDisabledError,
    FeatureFlag,
    FeatureFlagConfigManager,
)
from core.story import (
    SelectChoice,
    StoryCompiler,
    StoryRuntime,
    StoryRuntimeError,
    parse_story_project,
)
from test.unit.core.story.story_fixtures import campus_mystery_source


def _flags(enabled: bool = True) -> FeatureFlagConfigManager:
    return FeatureFlagConfigManager(
        environ={}, overrides={FeatureFlag.STORY_SYSTEM: enabled}
    )


def _runtime(*, global_progress: bool = False) -> StoryRuntime:
    source = campus_mystery_source()
    if global_progress:
        source["variables"]["world.progress"] = {
            "type": "integer",
            "scope": "global",
            "initial": 0,
            "min": 0,
            "max": 100,
            "visible": True,
        }
        source["narrativeGraph"]["nodes"][0]["choices"][0]["effects"].append(
            {"increment": ["world.progress", 1]}
        )
    program = StoryCompiler().compile(parse_story_project(source))
    return StoryRuntime(program)


def _choice(session: StorySession, command_id: str = "choice-1") -> SelectChoice:
    state = session.active_branch.state
    return SelectChoice(
        command_id=command_id,
        expected_revision=state.revision,
        choice_id="prepare-investigation",
        expected_node_id="transfer-day",
    )


def _enter_with_key(session: StorySession, command_id: str = "choice-2") -> SelectChoice:
    state = session.active_branch.state
    return SelectChoice(
        command_id=command_id,
        expected_revision=state.revision,
        choice_id="enter-with-key",
        expected_node_id="old-school-gate",
    )


def test_disabled_flag_prevents_session_creation_and_storage(tmp_path) -> None:
    repository = JsonStorySessionRepository(tmp_path / "session")

    with pytest.raises(FeatureDisabledError):
        StorySession.create(
            _runtime(),
            _flags(False),
            command_id="start-1",
            repository=repository,
        )

    assert not repository.path.exists()


def test_duplicate_command_returns_original_ack_without_advancing_revision() -> None:
    session = StorySession.create(_runtime(), _flags(), command_id="start-1")
    command = _choice(session)

    accepted = session.execute(command)
    duplicate = session.execute(command)

    assert duplicate.duplicate is True
    assert duplicate.event_ids == accepted.event_ids
    assert duplicate.revision == accepted.revision
    assert session.active_branch.state.revision == accepted.revision
    assert session.active_branch.generation == accepted.generation


def test_fork_restore_and_switch_preserve_branch_local_cast() -> None:
    session = StorySession.create(_runtime(), _flags(), command_id="start-1")
    session.execute(_choice(session))
    main_cast = session.active_branch.state.cast_state.active_character_ids

    fork = session.fork("alternate", generation=1)
    assert fork.state.current_node_id == "transfer-day"
    assert fork.state.cast_state.active_character_ids == ("ling",)

    session.switch_branch("main")
    assert session.active_branch.state.cast_state.active_character_ids == main_cast
    session.restore_generation(1)
    assert session.active_branch.state.current_node_id == "transfer-day"
    assert session.active_branch.state.cast_state.active_character_ids == ("ling",)


def test_session_round_trip_replays_identical_state_and_history(tmp_path) -> None:
    runtime = _runtime()
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    session = StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
        history_entries=({"role": "user", "content": "开始"},),
    )
    session.execute(
        _choice(session),
        history_entries=(
            {"role": "user", "content": "开始"},
            {"role": "assistant", "content": "你来到校门口。"},
        ),
    )

    recovered = StorySession.recover(
        runtime,
        _flags(),
        repository=repository,
        global_store=global_store,
    )

    assert recovered.active_branch.state == session.active_branch.state
    assert (
        recovered.active_branch.history_entries == session.active_branch.history_entries
    )
    assert recovered.chat_snapshot() == session.chat_snapshot()


def test_recovery_rejects_program_source_hash_mismatch(tmp_path) -> None:
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    runtime = _runtime()
    StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
    )
    with repository.path.open(encoding="utf-8") as file:
        payload = json.load(file)
    payload["branches"]["main"]["state"]["programSourceHash"] = "sha256:other"
    repository.save(payload)

    with pytest.raises(StoryProgramMismatchError):
        StorySession.recover(
            runtime,
            _flags(),
            repository=repository,
            global_store=global_store,
        )


def test_recovery_applies_pending_global_outbox_once(tmp_path) -> None:
    runtime = _runtime(global_progress=True)
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    session = StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
    )
    session.failure_injector = lambda point: (
        (_ for _ in ()).throw(RuntimeError("simulated crash"))
        if point == "after_session_commit"
        else None
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        session.execute(_choice(session))
    assert global_store.load(runtime.program).variables["world.progress"] == 0

    recovered = StorySession.recover(
        runtime,
        _flags(),
        repository=repository,
        global_store=global_store,
    )
    recovered_again = StorySession.recover(
        runtime,
        _flags(),
        repository=repository,
        global_store=global_store,
    )

    assert recovered.global_progress.variables["world.progress"] == 1
    assert recovered_again.global_progress.variables["world.progress"] == 1


def test_recovery_does_not_repeat_globally_applied_outbox(tmp_path) -> None:
    runtime = _runtime(global_progress=True)
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    session = StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
    )
    session.failure_injector = lambda point: (
        (_ for _ in ()).throw(RuntimeError("simulated crash"))
        if point == "after_global_apply"
        else None
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        session.execute(_choice(session))
    assert global_store.load(runtime.program).variables["world.progress"] == 1

    recovered = StorySession.recover(
        runtime,
        _flags(),
        repository=repository,
        global_store=global_store,
    )

    assert recovered.global_progress.variables["world.progress"] == 1


def test_causal_chain_tampering_is_rejected(tmp_path) -> None:
    runtime = _runtime()
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
    )
    payload = deepcopy(repository.load())
    assert payload is not None
    payload["branches"]["main"]["events"][1]["parentEventId"] = "wrong"
    repository.save(payload)

    with pytest.raises(ValueError, match="causal"):
        StorySession.recover(
            runtime,
            _flags(),
            repository=repository,
            global_store=global_store,
        )


def test_concurrent_choices_do_not_duplicate_event_groups(tmp_path) -> None:
    runtime = _runtime()
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    session = StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
    )
    revision = session.active_branch.state.revision

    def attempt(index: int) -> object:
        return session.execute(
            SelectChoice(
                command_id=f"choice-{index}",
                expected_revision=revision,
                choice_id="prepare-investigation",
                expected_node_id="transfer-day",
            )
        )

    accepted = []
    errors = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt, index) for index in range(8)]
        for future in as_completed(futures):
            try:
                accepted.append(future.result())
            except StoryRuntimeError as error:
                errors.append(error)

    assert len(accepted) == 1
    assert len(errors) == 7
    recovered = StorySession.recover(
        runtime,
        _flags(),
        repository=repository,
        global_store=global_store,
    )
    assert recovered.active_branch.state == session.active_branch.state
    assert recovered.active_branch.state.revision == accepted[0].revision


def test_set_variable_effects_round_trip_through_recovery(tmp_path) -> None:
    runtime = _runtime()
    repository = JsonStorySessionRepository(tmp_path / "session")
    global_store = JsonGlobalStoryProgressStore(tmp_path / "global")
    session = StorySession.create(
        runtime,
        _flags(),
        command_id="start-1",
        repository=repository,
        global_store=global_store,
    )
    session.execute(_choice(session))
    session.execute(_enter_with_key(session))

    recovered = StorySession.recover(
        runtime,
        _flags(),
        repository=repository,
        global_store=global_store,
    )

    assert recovered.active_branch.state == session.active_branch.state
    assert recovered.active_branch.state.variables["inventory"] == frozenset()


def test_long_story_ids_keep_distinct_global_progress_files() -> None:
    prefix = "a" * 100
    first = prefix + "left-branch-id"
    second = prefix + "right-branch-id"
    assert len(first) <= 128
    assert first[:100] == second[:100]
    assert global_progress_filename(first) != global_progress_filename(second)
