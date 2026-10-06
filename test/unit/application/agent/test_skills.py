from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
import yaml

from application.agent.skills import (
    BUNDLED_SKILL_NAMES,
    BUNDLED_SKILL_REFS,
    BUNDLED_SKILL_VERSION,
    bundled_skill_paths,
)
from sdk.agent import AgentRequestError
from test.unit.application.agent.test_pi_adapter import setup


def test_bundled_skills_are_portable_and_versioned():
    for reference, name in zip(BUNDLED_SKILL_REFS, BUNDLED_SKILL_NAMES):
        path = Path(bundled_skill_paths()[reference])
        text = path.read_text(encoding="utf-8")
        _, frontmatter, body = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert metadata["name"] == name == path.parent.name
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        assert len(name) <= 64
        assert 0 < len(metadata["description"]) <= 1024
        assert metadata["metadata"]["version"] == BUNDLED_SKILL_VERSION
        assert reference == f"skill:{name}@{BUNDLED_SKILL_VERSION}"
        assert body.strip()


def test_all_bundled_skill_instructions_are_available_without_read_tools(
    monkeypatch, tmp_path
):
    async def run():
        backend, config, _, _ = setup(monkeypatch, tmp_path, "normal")
        backend.config = backend.config.model_copy(
            update={
                "options": {
                    **backend.config.options,
                    "skills": bundled_skill_paths(),
                    "skillLoading": "preload",
                }
            }
        )
        session = await backend.open_session(
            config.model_copy(update={"skill_refs": BUNDLED_SKILL_REFS})
        )
        policy = (session.root / "policy.md").read_text(encoding="utf-8")
        for reference, source in bundled_skill_paths().items():
            assert reference in policy
            assert Path(source).read_text(encoding="utf-8") in policy
        for value in session.marker["skills"]:
            assert Path(value).name == "SKILL.md"
            assert Path(value).parent.name in BUNDLED_SKILL_NAMES
        assert len(policy.encode("utf-8")) <= 65536

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["preload", "native"])
def test_skill_and_policy_snapshots_survive_source_changes(monkeypatch, tmp_path, mode):
    async def run():
        backend, config, _, _ = setup(monkeypatch, tmp_path, "normal")
        source = tmp_path / "example" / "SKILL.md"
        source.parent.mkdir()
        original = "---\nname: example\ndescription: Test workflow.\n---\nOriginal instructions."
        source.write_text(original, encoding="utf-8")
        backend.config = backend.config.model_copy(
            update={
                "options": {
                    **backend.config.options,
                    "skills": {"skill:example@1": str(source)},
                    "skillLoading": mode,
                }
            }
        )
        config = config.model_copy(update={"skill_refs": ("skill:example@1",)})
        session = await backend.open_session(config)
        policy = (session.root / "policy.md").read_text(encoding="utf-8")
        assert (original in policy) == (mode == "preload")
        source.write_text("Changed instructions.", encoding="utf-8")
        Path(backend.config.options["policies"]["agent:default"]).write_text(
            "Changed policy.", encoding="utf-8"
        )
        restored = await backend.open_session(config)
        assert (restored.root / "policy.md").read_text(encoding="utf-8") == policy
        assert (
            Path(restored.marker["skills"][0]).read_text(encoding="utf-8") == original
        )

    asyncio.run(run())


def test_combined_skill_prompt_is_bounded(monkeypatch, tmp_path):
    async def run():
        backend, config, _, _ = setup(monkeypatch, tmp_path, "normal")
        skills = {}
        for name in ("one", "two"):
            path = tmp_path / name / "SKILL.md"
            path.parent.mkdir()
            path.write_text("x" * 35000, encoding="utf-8")
            skills[name] = str(path)
        backend.config = backend.config.model_copy(
            update={
                "options": {
                    **backend.config.options,
                    "skills": skills,
                    "skillLoading": "preload",
                }
            }
        )
        with pytest.raises(AgentRequestError) as error:
            await backend.open_session(
                config.model_copy(update={"skill_refs": tuple(skills)})
            )
        assert error.value.error.code == "LIMIT_EXCEEDED"
        assert not (tmp_path / "sessions" / config.session_id / "binding.json").exists()

    asyncio.run(run())
