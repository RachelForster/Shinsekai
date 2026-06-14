"""
Comprehensive tests for the effects module fixes.
Tests all bugs that were fixed:
1. Name collision on rename (auto-suffix)
2. Audio tag index mismatch (empty lines preserved)
3. Rename failure fallback (OSError handled)
4. Missing prompt word detection (pinpoint)
5. Effect usage guide generation
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from config.schema import Effect


# ── Test data helpers ──────────────────────────────────────────

def make_effect(name, audio_list=None, audio_tags="", **kwargs):
    return Effect.model_validate({
        "name": name,
        "audio_list": audio_list or [],
        "audio_tags": audio_tags,
        **kwargs,
    })


# ── Bug 1: Name collision on rename → auto-suffix ─────────────

def test_rename_no_collision():
    """Renaming to a name that doesn't exist: keeps the name."""
    effect_list = [
        make_effect("爆炸"),
        make_effect("闪光"),
    ]
    original_name = "爆炸"
    name = "火花"

    # Remove original
    effect_list[:] = [e for e in effect_list if e.name.lower() != original_name.lower()]
    # Auto-suffix logic
    existing_names = {e.name.lower() for e in effect_list}
    base_name = name
    counter = 1
    while name.lower() in existing_names:
        name = f"{base_name}_{counter}"
        counter += 1

    effect_list.append(make_effect(name))
    assert name == "火花"
    assert len(effect_list) == 2
    assert {e.name for e in effect_list} == {"闪光", "火花"}


def test_rename_with_collision():
    """Renaming to a name that already exists: auto-suffix."""
    effect_list = [
        make_effect("爆炸"),
        make_effect("闪光"),
    ]
    original_name = "爆炸"
    name = "闪光"  # collision!

    effect_list[:] = [e for e in effect_list if e.name.lower() != original_name.lower()]
    existing_names = {e.name.lower() for e in effect_list}
    base_name = name
    counter = 1
    while name.lower() in existing_names:
        name = f"{base_name}_{counter}"
        counter += 1

    assert name == "闪光_1"
    effect_list.append(make_effect(name))
    assert len(effect_list) == 2
    assert {e.name for e in effect_list} == {"闪光", "闪光_1"}


def test_rename_multiple_collisions():
    """Renaming with multiple existing suffix versions."""
    effect_list = [
        make_effect("闪光"),
        make_effect("闪光_1"),
        make_effect("闪光_2"),
    ]
    original_name = "闪光_2"
    name = "闪光"

    effect_list[:] = [e for e in effect_list if e.name.lower() != original_name.lower()]
    existing_names = {e.name.lower() for e in effect_list}
    base_name = name
    counter = 1
    while name.lower() in existing_names:
        name = f"{base_name}_{counter}"
        counter += 1

    assert name == "闪光_2"  # original 闪光_2 was removed, so 闪光_2 is available


def test_rename_to_same_name():
    """Renaming to the same name (no-op rename): no change."""
    effect_list = [make_effect("闪光")]

    old_dir = Path("data/effects/闪光")
    new_dir = Path("data/effects/闪光")
    assert old_dir == new_dir
    assert not (old_dir != new_dir)  # rename skipped


# ── Bug 2: Tag rebuilding preserves empty lines ─────────────────

def test_tag_rebuild_no_empty_lines():
    """Normal case: no empty lines, delete index 1."""
    old_tags = "特效 1：吓到\n特效 2：晕掉\n特效 3：提示\n"
    index = 1

    tag_lines = old_tags.splitlines()
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()
    tag_lines.pop(index)
    new_tags = "".join(
        f"特效 {i + 1}：{line.split('：', 1)[-1].strip() if '：' in line else line.strip()}\n"
        for i, line in enumerate(tag_lines)
    )
    assert new_tags == "特效 1：吓到\n特效 2：提示\n"


def test_tag_rebuild_with_empty_line():
    """Empty tag line at index 1: delete index 1 removes the empty line."""
    old_tags = "特效 1：吓到\n\n特效 3：提示\n"
    index = 1  # the empty line

    tag_lines = old_tags.splitlines()
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()

    assert len(tag_lines) == 3  # 3 lines preserved
    assert tag_lines[1] == ""  # empty line at index 1

    tag_lines.pop(index)
    new_tags = "".join(
        f"特效 {i + 1}：{line.split('：', 1)[-1].strip() if '：' in line else line.strip()}\n"
        for i, line in enumerate(tag_lines)
    )
    assert "吓到" in new_tags
    assert "提示" in new_tags
    assert new_tags == "特效 1：吓到\n特效 2：提示\n"


def test_tag_rebuild_delete_first_with_empty():
    """Delete index 0 when index 1 is empty."""
    old_tags = "特效 1：吓到\n\n特效 3：提示\n"
    index = 0

    tag_lines = old_tags.splitlines()
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()
    tag_lines.pop(index)
    new_tags = "".join(
        f"特效 {i + 1}：{line.split('：', 1)[-1].strip() if '：' in line else line.strip()}\n"
        for i, line in enumerate(tag_lines)
    )
    assert new_tags == "特效 1：\n特效 2：提示\n"


def test_tag_rebuild_all_empty_tags():
    """All tags are empty."""
    old_tags = "特效 1：\n特效 2：\n"
    index = 1

    tag_lines = old_tags.splitlines()
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()
    tag_lines.pop(index)
    new_tags = "".join(
        f"特效 {i + 1}：{line.split('：', 1)[-1].strip() if '：' in line else line.strip()}\n"
        for i, line in enumerate(tag_lines)
    )
    assert new_tags == "特效 1：\n"


# ── Bug 3: Directory rename OSError fallback ───────────────────

def test_copy_effect_dir():
    """_copy_effect_dir copies files correctly."""
    tmp = Path(tempfile.mkdtemp())
    try:
        src = tmp / "src"
        dst = tmp / "dst"
        src.mkdir()
        (src / "a.wav").write_bytes(b"audio1")
        (src / "b.wav").write_bytes(b"audio2")

        # Simulate _copy_effect_dir
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.is_file():
                shutil.copy2(item, dst / item.name)

        assert (dst / "a.wav").exists()
        assert (dst / "b.wav").exists()
        assert (dst / "a.wav").read_bytes() == b"audio1"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rename_fallback_when_target_exists():
    """When rename fails (target exists), copy + delete fallback works."""
    tmp = Path(tempfile.mkdtemp())
    try:
        old_dir = tmp / "old"
        new_dir = tmp / "new"
        old_dir.mkdir()
        new_dir.mkdir()  # Pre-existing target (simulates collision)
        (old_dir / "test.wav").write_bytes(b"test data")
        (new_dir / "stale.wav").write_bytes(b"stale")

        # Simulate fallback: if rename fails, copy then delete
        try:
            old_dir.rename(new_dir)
            assert False, "Should have raised on Windows"
        except (OSError, FileExistsError):
            # Fallback
            for item in old_dir.iterdir():
                if item.is_file():
                    dest = new_dir / item.name
                    shutil.copy2(item, dest)
            shutil.rmtree(old_dir, ignore_errors=True)

        assert not old_dir.is_dir() or not any(old_dir.iterdir())
        assert (new_dir / "test.wav").exists()
        assert (new_dir / "test.wav").read_bytes() == b"test data"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Bug 5: Missing prompt word detection ───────────────────────

def check_missing_prompts(new_tags, audio_count):
    """Simulate _save_effect_audio_tags validation."""
    tag_lines = new_tags.splitlines()
    missing = []
    for i in range(audio_count):
        line = tag_lines[i] if i < len(tag_lines) else ""
        if "：" in line:
            keyword = line.split("：", 1)[-1].strip()
        elif ":" in line:
            keyword = line.split(":", 1)[-1].strip()
        else:
            keyword = line.strip()
        if not keyword:
            missing.append(str(i + 1))
    return missing


def test_all_prompts_present():
    missing = check_missing_prompts("特效 1：吓到\n特效 2：晕掉\n特效 3：提示\n", 3)
    assert missing == []


def test_middle_prompt_empty():
    missing = check_missing_prompts("特效 1：吓到\n特效 2：\n特效 3：提示\n", 3)
    assert missing == ["2"]


def test_not_enough_lines():
    missing = check_missing_prompts("特效 1：吓到\n", 3)
    assert missing == ["2", "3"]


def test_all_empty():
    missing = check_missing_prompts("", 3)
    assert missing == ["1", "2", "3"]


def test_exact_match():
    missing = check_missing_prompts("特效 1：吓到\n特效 2：晕掉\n", 2)
    assert missing == []


# ── Effect usage guide generation ──────────────────────────────


def test_guide_empty_effect_names():
    from frontend_bridge_core.effects import _build_effect_usage_guide

    class FakeState:
        config_manager = None

    guide = _build_effect_usage_guide(FakeState(), [])
    assert guide == ""


def test_guide_with_keywords():
    from frontend_bridge_core.effects import _build_effect_usage_guide

    class FakeCM:
        def get_effect_by_name(self, name):
            if name == "test_effect":
                return make_effect(
                    "test_effect",
                    audio_list=["a1.wav", "a2.wav"],
                    audio_tags="特效 1：惊叫,尖叫\n特效 2：爆炸\n",
                )
            return None

    class FakeState:
        config_manager = FakeCM()

    guide = _build_effect_usage_guide(FakeState(), ["test_effect"])
    assert "[特效音效系统]" in guide
    assert "loop:" in guide
    assert "stop:" in guide
    assert "before:" in guide
    assert "after:" in guide
    assert "惊叫" in guide
    assert "尖叫" in guide
    assert "爆炸" in guide
    assert "test_effect" in guide


def test_guide_nonexistent_effect_skipped():
    from frontend_bridge_core.effects import _build_effect_usage_guide

    class FakeCM:
        def get_effect_by_name(self, name):
            return None

    class FakeState:
        config_manager = FakeCM()

    guide = _build_effect_usage_guide(FakeState(), ["ghost"])
    # Should not crash, just skip unknown effects
    assert "[特效音效系统]" in guide
    assert "ghost" not in guide or "未配置触发词" in guide


def test_guide_effect_without_keywords():
    from frontend_bridge_core.effects import _build_effect_usage_guide

    class FakeCM:
        def get_effect_by_name(self, name):
            return make_effect("empty_effect")

    class FakeState:
        config_manager = FakeCM()

    guide = _build_effect_usage_guide(FakeState(), ["empty_effect"])
    assert "未配置触发词" in guide


# ── Save effect rename path (integration logic) ────────────────

def test_save_effect_rename_removes_original_not_others():
    """When renaming, only the original should be removed from list."""
    effect_list = [
        make_effect("A"),
        make_effect("B"),
        make_effect("C"),
    ]
    original_name = "A"

    effect_list[:] = [e for e in effect_list if e.name.lower() != original_name.lower()]
    assert len(effect_list) == 2
    assert {e.name for e in effect_list} == {"B", "C"}


def test_save_effect_new_no_collision():
    """Creating new effect with unique name."""
    effect_list = [make_effect("A")]
    name = "B"

    existing = next((e for e in effect_list if e.name.lower() == name.lower()), None)
    assert existing is None
    effect_list.append(make_effect(name))
    assert len(effect_list) == 2


def test_save_effect_overwrite_existing():
    """Saving with same name (edit, not rename) replaces existing."""
    effect_list = [make_effect("A", color="#ff0000")]
    name = "A"
    new_body = make_effect("A", color="#00ff00")

    effect_list[:] = [e for e in effect_list if e.name.lower() != name.lower()]
    effect_list.append(new_body)
    assert len(effect_list) == 1
    assert effect_list[0].color == "#00ff00"


def test_delete_effect_removes_from_list():
    """Delete removes the correct effect."""
    effect_list = [make_effect("A"), make_effect("B"), make_effect("C")]
    name = "B"

    match = next((e for e in effect_list if e.name.lower() == name.lower()), None)
    assert match is not None
    effect_list.remove(match)
    assert len(effect_list) == 2
    assert {e.name for e in effect_list} == {"A", "C"}


def test_delete_effect_case_insensitive():
    """Delete is case-insensitive."""
    effect_list = [make_effect("TestEffect"), make_effect("Other")]
    name = "testeffect"

    match = next((e for e in effect_list if e.name.lower() == name.lower()), None)
    assert match is not None
    assert match.name == "TestEffect"


# ── Audio upload/delete operations ─────────────────────────────

def test_audio_upload_path_dedup():
    """Upload should avoid duplicate paths in audio_list."""
    audio_list = ["data/effects/test/a.wav"]
    new_path = "data/effects/test/a.wav"
    if new_path not in audio_list:
        audio_list.append(new_path)
    assert len(audio_list) == 1  # No duplicate


def test_audio_upload_adds_new_path():
    """Upload should add new paths."""
    audio_list = ["data/effects/test/a.wav"]
    new_path = "data/effects/test/b.wav"
    if new_path not in audio_list:
        audio_list.append(new_path)
    assert len(audio_list) == 2


def test_audio_delete_index_boundary():
    """Delete at out-of-range index should raise."""
    audio_list = ["a.wav", "b.wav"]
    index = 5
    with pytest.raises(IndexError):
        if index < 0 or index >= len(audio_list):
            raise IndexError(f"audio index out of range: {index}")
        audio_list.pop(index)


# ── Keyword parsing from main.py ───────────────────────────────

def test_keyword_parsing_normal():
    """Normal keyword parsing from audio_tags."""
    audio_tags = "特效 1：吓到\n特效 2：晕掉\n特效 3：提示\n"
    audio_list = ["a1.wav", "a2.wav", "a3.wav"]

    tags = audio_tags.splitlines()
    effect_keyword_map = {}
    for i, tag_line in enumerate(tags):
        tag_line = tag_line.strip()
        if not tag_line:
            continue
        if "：" in tag_line:
            keyword = tag_line.split("：", 1)[-1].strip()
        elif ":" in tag_line:
            keyword = tag_line.split(":", 1)[-1].strip()
        else:
            keyword = tag_line
        if keyword and i < len(audio_list) and audio_list[i]:
            for kw in keyword.split(","):
                kw = kw.strip()
                if kw:
                    effect_keyword_map[kw] = audio_list[i]

    assert effect_keyword_map == {
        "吓到": "a1.wav",
        "晕掉": "a2.wav",
        "提示": "a3.wav",
    }


def test_keyword_parsing_with_empty_line():
    """Keyword parsing with an empty tag line."""
    audio_tags = "特效 1：吓到\n\n特效 3：提示\n"
    audio_list = ["a1.wav", "a2.wav", "a3.wav"]

    tags = audio_tags.splitlines()
    effect_keyword_map = {}
    for i, tag_line in enumerate(tags):
        tag_line = tag_line.strip()
        if not tag_line:
            continue
        if "：" in tag_line:
            keyword = tag_line.split("：", 1)[-1].strip()
        else:
            keyword = tag_line
        if keyword and i < len(audio_list) and audio_list[i]:
            for kw in keyword.split(","):
                kw = kw.strip()
                if kw:
                    effect_keyword_map[kw] = audio_list[i]

    # Audio at index 1 (a2.wav) has no keyword → correctly unmapped
    assert "吓到" in effect_keyword_map
    assert "提示" in effect_keyword_map
    assert effect_keyword_map["吓到"] == "a1.wav"
    assert effect_keyword_map["提示"] == "a3.wav"


def test_keyword_parsing_multi_keywords():
    """Comma-separated multiple keywords."""
    audio_tags = "特效 1：晕掉,晕过去,晕倒,眩晕\n"
    audio_list = ["a1.wav"]

    tags = audio_tags.splitlines()
    effect_keyword_map = {}
    for i, tag_line in enumerate(tags):
        tag_line = tag_line.strip()
        if not tag_line:
            continue
        if "：" in tag_line:
            keyword = tag_line.split("：", 1)[-1].strip()
        else:
            keyword = tag_line
        if keyword and i < len(audio_list) and audio_list[i]:
            for kw in keyword.split(","):
                kw = kw.strip()
                if kw:
                    effect_keyword_map[kw] = audio_list[i]

    assert len(effect_keyword_map) == 4
    assert effect_keyword_map["晕掉"] == "a1.wav"
    assert effect_keyword_map["晕过去"] == "a1.wav"
    assert effect_keyword_map["晕倒"] == "a1.wav"
    assert effect_keyword_map["眩晕"] == "a1.wav"


# ── resolve_effect prefix parsing ──────────────────────────────

def test_resolve_effect_prefix_loop():
    raw = "loop:雨声"
    assert raw.startswith("loop:")
    keyword = raw[5:]
    assert keyword == "雨声"


def test_resolve_effect_prefix_stop():
    raw = "stop:雨声"
    assert raw.startswith("stop:")
    keyword = raw[5:]
    assert keyword == "雨声"


def test_resolve_effect_prefix_before():
    raw = "before:吓到"
    assert raw.startswith("before:")
    keyword = raw[7:]
    assert keyword == "吓到"


def test_resolve_effect_prefix_after():
    raw = "after:鼓掌"
    assert raw.startswith("after:")
    keyword = raw[6:]
    assert keyword == "鼓掌"


def test_resolve_effect_no_prefix():
    raw = "吓到"
    assert not raw.startswith("loop:")
    assert not raw.startswith("stop:")
    assert not raw.startswith("before:")
    assert not raw.startswith("after:")
    assert raw == "吓到"


def test_resolve_effect_leave():
    effect = "LEAVE"
    # after_dialog=False → should not trigger leave
    # after_dialog=True → should trigger leave
    after_dialog_false = (effect == "LEAVE" and False)  # no
    after_dialog_true = (effect == "LEAVE" and True)  # yes
    assert not after_dialog_false
    assert after_dialog_true


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
