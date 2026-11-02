from dataclasses import replace
import hashlib
import json

from application.story import (
    JsonGlobalStoryProgressStore,
    JsonStorySessionRepository,
    StorySession,
)
from core.story import StoryCompiler, StoryRuntime, parse_story_project
from core.story.compiler import canonical_json
from test.unit.application.story.test_session import _choice, _flags
from test.unit.core.story.story_fixtures import campus_mystery_source


def _programs():
    project = parse_story_project(campus_mystery_source())
    program = StoryCompiler().compile(project)
    # Reproduce the pre-backgrounds dataclass serialization independently of
    # the compiler's hashing path, including hashes nested inside saved states.
    old_document = json.loads(canonical_json(project))
    del old_document["metadata"]["backgrounds"]
    old_hash = hashlib.sha256(canonical_json(old_document).encode("utf-8")).hexdigest()
    return replace(program, source_hash=old_hash), program


def test_legacy_session_recovers_without_rewriting_saved_hashes(tmp_path):
    legacy, current = _programs()
    repository = JsonStorySessionRepository(tmp_path / "session")
    session = StorySession.create(
        StoryRuntime(legacy), _flags(), command_id="start", repository=repository
    )
    session.execute(_choice(session))

    recovered = StorySession.recover(
        StoryRuntime(current), _flags(), repository=repository,
        global_store=JsonGlobalStoryProgressStore(tmp_path / "global"),
    )

    assert current.source_hash == legacy.source_hash
    assert recovered.active_branch.state == session.active_branch.state
    assert recovered.active_branch.events == session.active_branch.events


def test_legacy_global_progress_allows_a_fresh_session(tmp_path):
    legacy, current = _programs()
    store = JsonGlobalStoryProgressStore(tmp_path / "global")
    progress = store.load(legacy)
    progress.unlocked_ending_ids.add("good-ending")
    progress.applied_outbox_ids.add("legacy:ending")
    store.save(progress)

    session = StorySession.create(
        StoryRuntime(current), _flags(), command_id="start", global_store=store
    )

    assert session.global_progress.unlocked_ending_ids == {"good-ending"}
    assert session.global_progress.applied_outbox_ids == {"legacy:ending"}


def test_background_suggestions_and_real_edits_still_affect_hash():
    source = campus_mystery_source()
    compiler = StoryCompiler()
    original = compiler.compile(parse_story_project(source)).source_hash
    source["metadata"]["backgrounds"] = []
    assert compiler.compile(parse_story_project(source)).source_hash == original
    source["metadata"]["backgrounds"] = ["旧校舍"]
    assert compiler.compile(parse_story_project(source)).source_hash != original
    source["metadata"].pop("backgrounds")
    source["title"] = "修改后的剧本"
    assert compiler.compile(parse_story_project(source)).source_hash != original
