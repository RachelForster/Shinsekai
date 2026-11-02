from __future__ import annotations

from copy import deepcopy

import pytest

from core.story import (
    RequestCharacterEntry,
    RequestCharacterExit,
    RequestCharacterReplace,
    SelectChoice,
    StartStory,
    StoryCompiler,
    StoryRuntime,
    StoryRuntimeError,
    parse_story_project,
)

from .story_fixtures import campus_mystery_source


def _runtime() -> StoryRuntime:
    source = deepcopy(campus_mystery_source())
    source["cast"]["characters"].extend(
        [
            {
                "id": "witness",
                "source": {
                    "type": "local-library",
                    "characterId": "witness",
                    "revision": "fixture-witness",
                },
            },
            {
                "id": "doctor",
                "source": {
                    "type": "local-library",
                    "characterId": "doctor",
                    "revision": "fixture-doctor",
                },
            },
        ]
    )
    gate = source["narrativeGraph"]["nodes"][1]
    gate["castPolicy"] = {
        "mode": "fixed",
        "required": ["ling", "detective-zhou"],
        "constraints": {"minActive": 2, "maxActive": 3},
    }
    gate["exposedContext"] = {
        "characterEntryReasonIds": ["door-opened"],
        "characterExitReasonIds": ["sent-home"],
        "characterReplaceReasonIds": ["medical-help"],
    }
    return StoryRuntime(StoryCompiler().compile(parse_story_project(source)))


def _gate(runtime: StoryRuntime):
    started = runtime.start(StartStory("start"))
    return runtime.execute(
        started.state,
        SelectChoice(
            "choice",
            started.state.revision,
            "prepare-investigation",
            "transfer-day",
        ),
    ).state


def test_registered_character_entry_exit_and_replace_are_revision_guarded() -> None:
    runtime = _runtime()
    gate = _gate(runtime)
    entered = runtime.execute(
        gate,
        RequestCharacterEntry(
            "entry",
            gate.revision,
            "witness",
            "door-opened",
            "old-school-gate",
        ),
    ).state
    replaced = runtime.execute(
        entered,
        RequestCharacterReplace(
            "replace",
            entered.revision,
            "witness",
            "doctor",
            "medical-help",
            "old-school-gate",
        ),
    ).state
    exited = runtime.execute(
        replaced,
        RequestCharacterExit(
            "exit",
            replaced.revision,
            "doctor",
            "sent-home",
            "old-school-gate",
        ),
    ).state

    assert entered.cast_state.active_character_ids[-1] == "witness"
    assert replaced.cast_state.active_character_ids[-1] == "doctor"
    assert exited.cast_state.active_character_ids == ("ling", "detective-zhou")


def test_character_request_rejects_unpublished_reason_and_required_exit() -> None:
    runtime = _runtime()
    gate = _gate(runtime)

    with pytest.raises(StoryRuntimeError) as reason_error:
        runtime.execute(
            gate,
            RequestCharacterEntry(
                "entry",
                gate.revision,
                "witness",
                "invented",
                "old-school-gate",
            ),
        )
    assert reason_error.value.code == "runtime.character_reason"

    with pytest.raises(StoryRuntimeError) as required_error:
        runtime.execute(
            gate,
            RequestCharacterExit(
                "exit",
                gate.revision,
                "ling",
                "sent-home",
                "old-school-gate",
            ),
        )
    assert required_error.value.code == "runtime.character_required"


def test_character_entry_requires_optional_query_and_copies_asset_constraints() -> None:
    source = deepcopy(campus_mystery_source())
    source["cast"]["characters"].extend(
        [
            {
                "id": "witness",
                "tags": ["witness"],
                "source": {
                    "type": "local-library",
                    "characterId": "witness",
                    "revision": "fixture-witness",
                },
            },
            {
                "id": "doctor",
                "tags": ["medical"],
                "source": {
                    "type": "local-library",
                    "characterId": "doctor",
                    "revision": "fixture-doctor",
                },
            },
        ]
    )
    gate = source["narrativeGraph"]["nodes"][1]
    gate["castPolicy"] = {
        "mode": "fixed",
        "required": ["ling", "detective-zhou"],
        "constraints": {
            "minActive": 2,
            "maxActive": 3,
            "requireLoadedAssets": True,
        },
        "fallback": {"onLoadFailure": "continue-without-optional"},
        "optionalQuery": {"allTags": ["witness"]},
    }
    gate["exposedContext"] = {
        "characterEntryReasonIds": ["door-opened"],
        "characterReplaceReasonIds": ["medical-help"],
    }
    runtime = StoryRuntime(StoryCompiler().compile(parse_story_project(source)))
    state = _gate(runtime)

    entered = runtime.execute(
        state,
        RequestCharacterEntry(
            "entry",
            state.revision,
            "witness",
            "door-opened",
            "old-school-gate",
        ),
    )
    assert entered.cast_plans[-1].requires_loaded_assets is True
    assert entered.cast_plans[-1].on_load_failure == "continue-without-optional"
    assert "witness" not in entered.cast_plans[-1].required_character_ids

    with pytest.raises(StoryRuntimeError) as error:
        runtime.execute(
            entered.state,
            RequestCharacterReplace(
                "replace",
                entered.state.revision,
                "witness",
                "doctor",
                "medical-help",
                "old-school-gate",
            ),
        )
    assert error.value.code == "runtime.character_ineligible"
